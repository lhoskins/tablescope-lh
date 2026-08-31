"""Fix UserVDB/SharedVDB rows still on the pre-2026-05-23 per-VDB username
scheme (e.g. ``vdb_user_6426044``, ``vdb_shared_933455``). Dry-run by default.

Since commit 1b319879 ("fix: use test/test credentials for Teiid PG wire
authentication"), every VDB is provisioned with the fixed ``test``/``test``
credentials matching WildFly's ``application-users.properties`` -- the
``teiid-security`` domain's ``RealmDirect`` login module only knows about
that one user. Per-VDB isolation is provided by the VDB *name*, not by a
separate WildFly account per VDB, so there is no user to add for a stray
username; the row itself is what's wrong.

Any row with ``vdb_username != "test"`` predates that fix and will fail
Teiid PG-wire authentication (``TEIID50072``) forever, since WildFly never
had (and, per that fix, never needs) an account matching it. This script
rewrites such rows to the current scheme. Idempotent: a row already on
``test`` is left untouched, so this is safe to re-run.

Run backfill_vdb_password_encryption.py first (or after; order does not
matter) -- that script only re-encodes whatever password value is already
stored, so it will not touch the value this script writes if run first, and
this script writes an already-encrypted value if run first.

Usage:
    python -m scripts.fix_legacy_vdb_test_credentials            # dry run
    python -m scripts.fix_legacy_vdb_test_credentials --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.crypto import encrypt_secret

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_CURRENT_USERNAME = "test"
_CURRENT_PASSWORD = "test"


async def _fix_model(model, *, apply: bool) -> tuple[int, int]:
    scanned = 0
    rewritten = 0
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(model).where(model.vdb_username != _CURRENT_USERNAME)
            )
        ).all()
        scanned = len(rows)
        for row in rows:
            rewritten += 1
            logger.info(
                "%s id=%s tenant_id=%s vdb_id=%s: username %r %s %r",
                model.__name__,
                row.id,
                row.tenant_id,
                row.vdb_id,
                row.vdb_username,
                "would become" if not apply else "becoming",
                _CURRENT_USERNAME,
            )
            if apply:
                row.vdb_username = _CURRENT_USERNAME
                row.encrypted_password = encrypt_secret(_CURRENT_PASSWORD)
        if apply and rewritten:
            await session.commit()
    return scanned, rewritten


async def main(apply: bool) -> None:
    for model in (UserVDB, SharedVDB):
        scanned, rewritten = await _fix_model(model, apply=apply)
        logger.info(
            "%s: found %d legacy row(s), %s %d",
            model.__name__,
            scanned,
            "fixed" if apply else "would fix",
            rewritten,
        )
    if not apply:
        logger.info("Dry run complete. Re-run with --apply to write changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
