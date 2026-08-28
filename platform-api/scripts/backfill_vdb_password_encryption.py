"""Re-encrypt any UserVDB/SharedVDB row whose encrypted_password is still
plaintext (TS-ISO-008). Dry-run by default.

New rows are encrypted at write time (see the write sites in
tenants_crud.py, tenants_users.py, tenant_data_planes_crud.py,
tenant_onboarding_service.py, project_sharing.py) and
get_decrypted_password() dual-reads (tries Fernet, falls back to the raw
value) so old plaintext rows keep working without this script -- but they
stay plaintext at rest until it runs. Idempotent: a row that is already
valid Fernet ciphertext is left untouched, so this is safe to re-run.

Usage:
    python -m scripts.backfill_vdb_password_encryption            # dry run
    python -m scripts.backfill_vdb_password_encryption --apply    # write
    python -m scripts.backfill_vdb_password_encryption --apply --batch-size 100
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.crypto import decrypt_secret, encrypt_secret

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_already_encrypted(value: str) -> bool:
    try:
        decrypt_secret(value)
        return True
    except Exception:
        return False


async def _backfill_model(model, *, apply: bool, batch_size: int) -> tuple[int, int]:
    scanned = 0
    rewritten = 0
    async with SessionLocal() as session:
        rows = (await session.scalars(select(model))).all()
        for row in rows:
            scanned += 1
            if _is_already_encrypted(row.encrypted_password):
                continue
            rewritten += 1
            logger.info(
                "%s id=%s tenant_id=%s: plaintext password %s",
                model.__name__,
                row.id,
                row.tenant_id,
                "would be re-encrypted" if not apply else "re-encrypting",
            )
            if apply:
                row.encrypted_password = encrypt_secret(row.encrypted_password)
                if rewritten % batch_size == 0:
                    await session.commit()
        if apply:
            await session.commit()
    return scanned, rewritten


async def main(apply: bool, batch_size: int) -> None:
    for model in (UserVDB, SharedVDB):
        scanned, rewritten = await _backfill_model(model, apply=apply, batch_size=batch_size)
        logger.info(
            "%s: scanned %d row(s), %s %d",
            model.__name__,
            scanned,
            "re-encrypted" if apply else "would re-encrypt",
            rewritten,
        )
    if not apply:
        logger.info("Dry run complete. Re-run with --apply to write changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    parser.add_argument("--batch-size", type=int, default=200, help="Commit every N rewritten rows")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply, batch_size=args.batch_size))
