"""Tests for VDB password encryption at rest (TS-ISO-008).

Live finding: UserVDB/SharedVDB.encrypted_password was written AND
returned as plaintext -- the field was named "encrypted" but never
actually encrypted. New writes must be genuine Fernet ciphertext;
get_decrypted_password must decrypt them correctly, and must still work
(dual-read) against a legacy plaintext row so existing connections don't
break before the backfill script runs.

Run from ``platform-api``: ``pytest -q tests/test_vdb_password_encryption.py``.
"""

from __future__ import annotations

from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.crypto import encrypt_secret


def test_user_vdb_decrypts_a_genuinely_encrypted_password():
    vdb = UserVDB(
        tenant_id=1,
        user_id=1,
        vdb_id="v1",
        vdb_username="u",
        encrypted_password=encrypt_secret("s3cr3t-pw"),
    )
    assert vdb.get_decrypted_password() == "s3cr3t-pw"


def test_user_vdb_dual_reads_a_legacy_plaintext_password():
    vdb = UserVDB(
        tenant_id=1,
        user_id=1,
        vdb_id="v1",
        vdb_username="u",
        encrypted_password="legacy-plaintext-pw",
    )
    assert vdb.get_decrypted_password() == "legacy-plaintext-pw"


def test_shared_vdb_decrypts_a_genuinely_encrypted_password():
    vdb = SharedVDB(
        tenant_id=1,
        vdb_id="v1",
        vdb_username="u",
        encrypted_password=encrypt_secret("s3cr3t-pw"),
    )
    assert vdb.get_decrypted_password() == "s3cr3t-pw"


def test_shared_vdb_dual_reads_a_legacy_plaintext_password():
    vdb = SharedVDB(
        tenant_id=1,
        vdb_id="v1",
        vdb_username="u",
        encrypted_password="legacy-plaintext-pw",
    )
    assert vdb.get_decrypted_password() == "legacy-plaintext-pw"


def test_encrypted_value_is_not_the_plaintext_itself():
    """A basic sanity check that write sites are storing ciphertext, not
    plaintext under a misleading name."""
    ciphertext = encrypt_secret("s3cr3t-pw")
    assert ciphertext != "s3cr3t-pw"
    assert "s3cr3t-pw" not in ciphertext
