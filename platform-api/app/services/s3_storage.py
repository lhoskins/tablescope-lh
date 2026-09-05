"""S3 persistence with fail-closed tenant-private bindings."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings
from app.services.tenant_storage_resolver import StorageBinding, StorageIsolationError

logger = logging.getLogger(__name__)


class S3StorageService:
    """Manage shared storage or one explicitly resolved tenant boundary."""

    def __init__(self, binding: StorageBinding | None = None) -> None:
        if binding is None:
            settings = get_settings()
            binding = StorageBinding(
                bucket_name=settings.s3_bucket_name,
                region=settings.s3_region,
                prefix="",
                local_base=Path(settings.customer_base_path),
            )
        self._binding = binding
        self._bucket = binding.access_point_arn or binding.bucket_name
        self._region = binding.region
        self._local_base = binding.local_base
        self._client = self._build_client()

    def _build_client(self) -> Any:
        kwargs: dict = {"region_name": self._region}
        if self._binding.endpoint_url:
            kwargs["endpoint_url"] = self._binding.endpoint_url
        if self._binding.dedicated:
            if not all(
                (
                    self._binding.role_arn,
                    self._binding.access_point_arn,
                    self._binding.endpoint_url,
                    self._binding.kms_key_arn,
                    self._binding.vpc_endpoint_id,
                    self._binding.force_private,
                )
            ):
                raise StorageIsolationError("dedicated storage binding is incomplete")
            sts = boto3.client("sts", region_name=self._region)
            assumed = sts.assume_role(
                RoleArn=self._binding.role_arn,
                RoleSessionName=f"tablescope-storage-{uuid.uuid4().hex[:12]}",
            )["Credentials"]
            kwargs.update(
                aws_access_key_id=assumed["AccessKeyId"],
                aws_secret_access_key=assumed["SecretAccessKey"],
                aws_session_token=assumed["SessionToken"],
            )
        return boto3.client("s3", **kwargs)

    @property
    def bucket_name(self) -> str:
        return self._binding.bucket_name

    @property
    def is_dedicated(self) -> bool:
        return self._binding.dedicated

    def _key(self, key: str) -> str:
        return self._binding.key(key)

    def _encryption_args(self) -> dict[str, str]:
        if not self._binding.dedicated:
            return {}
        assert self._binding.kms_key_arn
        return {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._binding.kms_key_arn,
        }

    def ensure_bucket_exists(self) -> None:
        """Create only the legacy shared bucket; Terraform owns tenant buckets."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if self._binding.dedicated:
                raise StorageIsolationError("tenant S3 boundary is unavailable") from exc
            error_code = exc.response["Error"]["Code"]
            if error_code not in ("404", "NoSuchBucket"):
                raise
            if self._region == "us-east-1":
                self._client.create_bucket(Bucket=self._bucket)
            else:
                self._client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region},
                )

    def upload_file(self, local_path: str, s3_key: str) -> str:
        key = self._key(s3_key)
        extra = self._encryption_args()
        if extra:
            self._client.upload_file(local_path, self._bucket, key, ExtraArgs=extra)
        else:
            self._client.upload_file(local_path, self._bucket, key)
        uri = f"s3://{self._binding.bucket_name}/{key}"
        logger.info("Uploaded %s -> %s", local_path, uri)
        return uri

    def download_file(self, s3_key: str, local_path: str) -> str:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        self._client.download_file(self._bucket, self._key(s3_key), local_path)
        return local_path

    def delete_file(self, s3_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(s3_key))

    def list_files(self, prefix: str) -> list[dict]:
        effective_prefix = self._key(prefix)
        result = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=effective_prefix):
            for obj in page.get("Contents", []):
                result.append(
                    {
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    }
                )
        return result

    def file_exists(self, s3_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(s3_key))
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if self._binding.dedicated and code not in ("404", "NoSuchKey", "NotFound"):
                raise
            return False

    def sync_local_to_s3(self, local_dir: str, s3_prefix: str) -> int:
        local_path = Path(local_dir)
        if not local_path.is_dir():
            if self._binding.dedicated:
                raise StorageIsolationError(f"required local directory does not exist: {local_dir}")
            return 0
        count = 0
        for root, _dirs, files in os.walk(local_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                relative = os.path.relpath(filepath, local_dir)
                self.upload_file(filepath, f"{s3_prefix}/{relative}".replace("\\", "/"))
                count += 1
        return count

    def sync_s3_to_local(self, s3_prefix: str, local_dir: str) -> int:
        count = 0
        effective_prefix = self._key(s3_prefix)
        for item in self.list_files(s3_prefix):
            full_key = item["key"]
            relative = full_key[len(effective_prefix) :].lstrip("/")
            if not relative:
                continue
            local_path = os.path.join(local_dir, relative)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self._client.download_file(self._bucket, full_key, local_path)
            count += 1
        return count

    def validate_private_boundary(self) -> None:
        """Round-trip a probe and prove the tenant CMK protected it."""
        if not self._binding.dedicated:
            raise StorageIsolationError("private-boundary validation requires dedicated storage")
        probe_key = self._key(f".tablescope-health/{uuid.uuid4().hex}")
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=probe_key,
                Body=b"tablescope-storage-boundary-probe",
                **self._encryption_args(),
            )
            head = self._client.head_object(Bucket=self._bucket, Key=probe_key)
            if head.get("ServerSideEncryption") != "aws:kms":
                raise StorageIsolationError("probe object was not encrypted with SSE-KMS")
            if head.get("SSEKMSKeyId") != self._binding.kms_key_arn:
                raise StorageIsolationError("probe object was not encrypted with the tenant CMK")
            body = self._client.get_object(Bucket=self._bucket, Key=probe_key)["Body"].read()
            if body != b"tablescope-storage-boundary-probe":
                raise StorageIsolationError("tenant S3 probe returned unexpected content")
        finally:
            try:
                self._client.delete_object(Bucket=self._bucket, Key=probe_key)
            except Exception:
                logger.warning("Could not delete tenant S3 health probe %s", probe_key, exc_info=True)

    def get_s3_key_for_upload(self, tenant_id: int, user_id: int, filename: str) -> str:
        return f"customers/{tenant_id}/{user_id}/uploads/{filename}"

    def get_s3_key_for_vdb(self, tenant_id: int, user_id: int, vdb_id: str) -> str:
        return f"customers/{tenant_id}/{user_id}/vdb/{vdb_id}-vdb.xml"

    def get_s3_key_for_shared_vdb(self, tenant_id: int, vdb_id: str) -> str:
        return f"customers/{tenant_id}/shared/vdb/{vdb_id}-vdb.xml"

    def get_s3_key_for_shared_upload(self, tenant_id: int, filename: str) -> str:
        return f"customers/{tenant_id}/shared/uploads/{filename}"
