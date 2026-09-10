"""Regression test: one credential's failure must not poison the rest.

``refresh_google_drive_tokens`` processes every Google Drive
``ConnectorCredential`` in one session, committing after each success and
rolling back after each failure. ``Session.rollback()`` unconditionally
expires every object in the session's identity map -- regardless of
``expire_on_commit`` -- so an earlier credential's failure (any exception
that escapes ``_refresh_google_drive_credential``/re-registration, not just a
``GoogleOAuthError``, which is caught locally) expired every credential still
waiting to be processed. The next credential's synchronous
``credential.secret_encrypted`` read inside ``decrypt_config`` then hit an
expired attribute outside an awaited context, raising
``sqlalchemy.exc.MissingGreenlet`` -- surfaced as
``SaasSourceError("Stored connector credential could not be read.")`` -- so a
single bad credential silently broke every credential after it in the same
run.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.connector_credential import ConnectorCredential
from app.models.tenant import Tenant
from app.services.crypto import decrypt_secret, encrypt_secret
from app.tasks import google_drive_token_refresh as task


async def test_one_credentials_failure_does_not_poison_the_next(
    db_engine, monkeypatch
):
    # The task module imports SessionLocal at call time inside each function
    # (`async with SessionLocal() as session`), so patching the module-level
    # name is enough to redirect every session it opens to the test engine.
    # Seed data through this same factory, and close the setup session
    # before running the task, rather than holding a second session open
    # concurrently (as the shared `db_session` fixture would) -- production
    # never has an unrelated session open across this cron job's run, and an
    # extra concurrently-open session against the same in-memory sqlite
    # engine changes rollback/detach behavior in ways that don't reflect the
    # real bug this test targets.
    test_sessions = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(task, "SessionLocal", test_sessions)

    two_credentials = []
    async with test_sessions() as session:
        tenant = Tenant(slug="acme", name="Acme")
        session.add(tenant)
        await session.flush()
        for i in (1, 2):
            credential = ConnectorCredential(
                tenant_id=tenant.id,
                connector_type="google_drive",
                display_name=f"Google Drive {i}",
                secret_encrypted=encrypt_secret(
                    json.dumps({"refresh_token": f"rt-{i}"})
                ),
            )
            session.add(credential)
            await session.flush()
            two_credentials.append(credential.id)
        await session.commit()

    async def fake_refresh_access_token(*, refresh_token: str) -> dict:
        if refresh_token == "rt-1":
            # Anything other than gd.GoogleOAuthError -- that one is caught
            # inside _refresh_google_drive_credential and never reaches the
            # outer loop's except/rollback at all.
            raise RuntimeError("simulated transient failure for credential 1")
        return {"access_token": "new-access-token", "refresh_token": "rt-2-rotated"}

    monkeypatch.setattr(task.gd, "refresh_access_token", fake_refresh_access_token)

    result = await task.refresh_google_drive_tokens({})

    assert result["refreshed"] == 1, (
        "credential 2 should refresh successfully even though credential 1 "
        "failed first in the same run"
    )

    async with test_sessions() as session:
        credential_2 = await session.get(ConnectorCredential, two_credentials[1])
        config = json.loads(decrypt_secret(credential_2.secret_encrypted))
        assert config["access_token"] == "new-access-token"

        credential_1 = await session.get(ConnectorCredential, two_credentials[0])
        config_1 = json.loads(decrypt_secret(credential_1.secret_encrypted))
        assert config_1["refresh_token"] == "rt-1", "credential 1's rotation must have rolled back"
