"""Tests for scripts/fix_legacy_vdb_test_credentials.py.

Live finding: UserVDB/SharedVDB rows provisioned before commit 1b319879
("fix: use test/test credentials for Teiid PG wire authentication") still
carry the old per-VDB username scheme (``vdb_user_{vdb_id}``,
``vdb_shared_{vdb_id}``). WildFly's ``application-users.properties`` only
ever registers ``test`` (checked in this repo, unchanged since that fix),
so those rows fail Teiid PG-wire authentication (``TEIID50072``) forever.
This script rewrites them to the current ``test``/``test`` scheme.

Run from ``platform-api``: ``pytest -q tests/test_fix_legacy_vdb_test_credentials.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.crypto import encrypt_secret
from scripts import fix_legacy_vdb_test_credentials as script

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _patch_session_local(db_engine, monkeypatch):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(script, "SessionLocal", session_factory)


async def test_dry_run_reports_but_does_not_change_legacy_rows(db_session):
    row = UserVDB(
        tenant_id=1,
        user_id=1,
        vdb_id="6426044",
        vdb_username="vdb_user_6426044",
        encrypted_password=encrypt_secret("old-secret"),
    )
    db_session.add(row)
    await db_session.commit()

    scanned, rewritten = await script._fix_model(UserVDB, apply=False)
    assert scanned == 1
    assert rewritten == 1  # "would fix" count, same convention as the backfill script

    await db_session.refresh(row)
    assert row.vdb_username == "vdb_user_6426044"  # dry run: nothing actually written


async def test_apply_rewrites_legacy_user_vdb_to_test_credentials(db_session):
    row = UserVDB(
        tenant_id=1,
        user_id=1,
        vdb_id="6426044",
        vdb_username="vdb_user_6426044",
        encrypted_password=encrypt_secret("old-secret"),
    )
    db_session.add(row)
    await db_session.commit()

    scanned, rewritten = await script._fix_model(UserVDB, apply=True)
    assert scanned == 1
    assert rewritten == 1

    await db_session.refresh(row)
    assert row.vdb_username == "test"
    assert row.get_decrypted_password() == "test"


async def test_apply_rewrites_legacy_shared_vdb_to_test_credentials(db_session):
    row = SharedVDB(
        tenant_id=1,
        vdb_id="933455",
        vdb_username="vdb_shared_933455",
        encrypted_password=encrypt_secret("old-secret"),
    )
    db_session.add(row)
    await db_session.commit()

    scanned, rewritten = await script._fix_model(SharedVDB, apply=True)
    assert scanned == 1
    assert rewritten == 1

    await db_session.refresh(row)
    assert row.vdb_username == "test"
    assert row.get_decrypted_password() == "test"


async def test_row_already_on_test_credentials_is_left_untouched(db_session):
    row = UserVDB(
        tenant_id=1,
        user_id=1,
        vdb_id="1234567",
        vdb_username="test",
        encrypted_password=encrypt_secret("test"),
    )
    db_session.add(row)
    await db_session.commit()

    scanned, rewritten = await script._fix_model(UserVDB, apply=True)
    assert scanned == 0
    assert rewritten == 0
