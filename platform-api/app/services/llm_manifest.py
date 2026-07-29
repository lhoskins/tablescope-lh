"""Canonical signed manifests for LLM artifacts.

The manifest is a deterministic JSON document containing every hash and
metadata field the agent needs to verify an artifact. It is signed with an
Ed25519 key that the platform API holds privately; the deployment agent bakes
the corresponding public key into its image so it never has to fetch it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.config import get_settings


def _canonical_json(value: dict[str, Any]) -> bytes:
    """Sort keys and use compact separators for deterministic hashing/signing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _ensure_signing_key(key_path: str) -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    """Load or generate an Ed25519 signing key pair, returning (private, public, fingerprint)."""
    public_path = key_path + ".pub"
    if os.path.exists(key_path) and os.path.exists(public_path):
        with open(key_path, "rb") as fh:
            private_key = serialization.load_pem_private_key(fh.read(), password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Configured signing key is not an Ed25519 key")
        private = private_key
        with open(public_path, "rb") as fh:
            public_key = serialization.load_pem_public_key(fh.read())
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("Configured signing public key is not an Ed25519 key")
        public = public_key
    else:
        private = Ed25519PrivateKey.generate()
        public = private.public_key()
        os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True, mode=0o700)
        private_pem = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with open(os.open(key_path, os.O_CREAT | os.O_WRONLY, 0o600), "wb") as fh:
            fh.write(private_pem)
        with open(os.open(public_path, os.O_CREAT | os.O_WRONLY, 0o644), "wb") as fh:
            fh.write(public_pem)

    fingerprint = hashlib.sha256(
        public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    return private, public, fingerprint


def _get_signing_key() -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    settings = get_settings()
    key_path = settings.llm_manifest_signing_key_path
    if not key_path:
        raise RuntimeError("llm_manifest_signing_key_path is not configured")
    return _ensure_signing_key(key_path)


def get_public_key_fingerprint() -> str:
    """Return the fingerprint of the active manifest-signing public key."""
    return _get_signing_key()[2]


def sign_manifest(manifest: dict[str, Any]) -> tuple[str, str]:
    """Sign a canonical manifest and return (signature_base64, public_key_fingerprint)."""
    private, _, fingerprint = _get_signing_key()
    payload = _canonical_json(manifest)
    signature = private.sign(payload)
    return base64.b64encode(signature).decode("ascii"), fingerprint


def verify_manifest(manifest: dict[str, Any], signature_b64: str, public_key_pem: bytes) -> bool:
    """Verify a manifest signature against a PEM-encoded Ed25519 public key."""
    public: Ed25519PublicKey = serialization.load_pem_public_key(public_key_pem)  # type: ignore[assignment]
    payload = _canonical_json(manifest)
    signature = base64.b64decode(signature_b64)
    try:
        public.verify(signature, payload)
        return True
    except Exception:
        return False


def build_manifest(
    artifact_id: int,
    repo_url: str | None,
    commit_sha: str | None,
    quantization: str | None,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the canonical manifest for an artifact."""
    return {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "quantization": quantization,
        "format": "gguf",
        "files": sorted(files, key=lambda f: f["filename"]),
    }
