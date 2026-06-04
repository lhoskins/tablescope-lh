"""S3 storage service for VDB files and uploads.

Provides a dual-write strategy: files are stored both on S3 (canonical)
and on the local filesystem (for Teiid access). S3 serves as the
persistent, durable store while the local copy is needed because Teiid's
Excel translator reads from ParentDirectory on disk.

Directory structure on S3 mirrors local:
  s3://{bucket}/customers/{tenant_id}/{user_id}/uploads/{file}
  s3://{bucket}/customers/{tenant_id}/{user_id}/vdb/{vdb_id}-vdb.xml
  s3://{bucket}/customers/{tenant_id}/shared/vdb/{vdb_id}-vdb.xml
  s3://{bucket}/customers/{tenant_id}/shared/uploads/{file}
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

logger = logging.getLogger(__name__)


class S3StorageService:
    """Manages S3 bucket operations for VDB files and uploads."""

    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket_name
        self._region = settings.s3_region
        self._local_base = Path(settings.customer_base_path)
        self._client = boto3.client("s3", region_name=self._region)

    @property
    def bucket_name(self) -> str:
        return self._bucket

    def ensure_bucket_exists(self) -> None:
        """Create the S3 bucket if it doesn't exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            logger.info("S3 bucket %s already exists", self._bucket)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("404", "NoSuchBucket"):
                logger.info("Creating S3 bucket %s in %s", self._bucket, self._region)
                if self._region == "us-east-1":
                    self._client.create_bucket(Bucket=self._bucket)
                else:
                    self._client.create_bucket(
                        Bucket=self._bucket,
                        CreateBucketConfiguration={"LocationConstraint": self._region},
                    )
                logger.info("S3 bucket %s created", self._bucket)
            else:
                raise

    def upload_file(self, local_path: str, s3_key: str) -> str:
        """Upload a file to S3 and return the S3 URI."""
        self._client.upload_file(local_path, self._bucket, s3_key)
        uri = f"s3://{self._bucket}/{s3_key}"
        logger.info("Uploaded %s -> %s", local_path, uri)
        return uri

    def download_file(self, s3_key: str, local_path: str) -> str:
        """Download a file from S3 to local path."""
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        self._client.download_file(self._bucket, s3_key, local_path)
        logger.info("Downloaded s3://%s/%s -> %s", self._bucket, s3_key, local_path)
        return local_path

    def delete_file(self, s3_key: str) -> None:
        """Delete a file from S3."""
        self._client.delete_object(Bucket=self._bucket, Key=s3_key)
        logger.info("Deleted s3://%s/%s", self._bucket, s3_key)

    def list_files(self, prefix: str) -> list[dict]:
        """List files in S3 under a prefix."""
        result = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                result.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                })
        return result

    def file_exists(self, s3_key: str) -> bool:
        """Check if a file exists in S3."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=s3_key)
            return True
        except ClientError:
            return False

    def sync_local_to_s3(self, local_dir: str, s3_prefix: str) -> int:
        """Sync a local directory tree to S3. Returns count of files uploaded."""
        count = 0
        local_path = Path(local_dir)
        if not local_path.is_dir():
            logger.warning("Local directory %s does not exist", local_dir)
            return 0

        for root, _dirs, files in os.walk(local_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                relative = os.path.relpath(filepath, local_dir)
                s3_key = f"{s3_prefix}/{relative}".replace("\\", "/")
                self.upload_file(filepath, s3_key)
                count += 1

        logger.info("Synced %d files from %s to s3://%s/%s", count, local_dir, self._bucket, s3_prefix)
        return count

    def sync_s3_to_local(self, s3_prefix: str, local_dir: str) -> int:
        """Sync S3 prefix to local directory. Returns count of files downloaded."""
        count = 0
        files = self.list_files(s3_prefix)
        for f in files:
            s3_key = f["key"]
            relative = s3_key[len(s3_prefix):].lstrip("/")
            if not relative:
                continue
            local_path = os.path.join(local_dir, relative)
            self.download_file(s3_key, local_path)
            count += 1

        logger.info("Synced %d files from s3://%s/%s to %s", count, self._bucket, s3_prefix, local_dir)
        return count

    def get_s3_key_for_upload(self, tenant_id: int, user_id: int, filename: str) -> str:
        """Get the S3 key for a user upload file."""
        return f"customers/{tenant_id}/{user_id}/uploads/{filename}"

    def get_s3_key_for_vdb(self, tenant_id: int, user_id: int, vdb_id: str) -> str:
        """Get the S3 key for a user VDB file."""
        return f"customers/{tenant_id}/{user_id}/vdb/{vdb_id}-vdb.xml"

    def get_s3_key_for_shared_vdb(self, tenant_id: int, vdb_id: str) -> str:
        """Get the S3 key for a shared VDB file."""
        return f"customers/{tenant_id}/shared/vdb/{vdb_id}-vdb.xml"

    def get_s3_key_for_shared_upload(self, tenant_id: int, filename: str) -> str:
        """Get the S3 key for a shared upload file."""
        return f"customers/{tenant_id}/shared/uploads/{filename}"
