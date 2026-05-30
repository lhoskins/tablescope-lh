"""Symmetric encryption for sensitive data-source secrets.

Database data-source passwords must never be stored in plain text.  We use
Fernet (AES-128-CBC + HMAC) from the ``cryptography`` package.

The key comes from ``TABLESCOPE_SECRET_KEY`` when set.  Operators should set
this to a stable, URL-safe base64 32-byte key (``Fernet.generate_key()``).
When unset, we deterministically derive a key from ``JWT_SECRET_KEY`` so local
development works without extra configuration — but values encrypted with a
derived key become unreadable if the JWT secret changes, so production should
always set an explicit key.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    raw = settings.tablescope_secret_key.strip()
    if raw:
        key = raw.encode("utf-8")
        # Allow either a proper Fernet key or an arbitrary passphrase.
        try:
            Fernet(key)
            return Fernet(key)
        except (ValueError, TypeError):
            digest = hashlib.sha256(key).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    # Fallback: derive from the JWT secret.
    digest = hashlib.sha256(settings.jwt_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret, returning a URL-safe token string."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - corrupted/rotated key
        raise ValueError("Unable to decrypt secret (key mismatch?)") from exc
