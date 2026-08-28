"""Tests for chat attachment context authorization (TS-ISO-006).

Live finding: build_attachment_context resolved attachments by tenant_id
plus caller-supplied attachment_ids only -- any same-tenant user could
reference another user's (or another conversation's) attachment id and have
its extracted document text injected into their own conversation as model
context. It must now require the attachment to belong to the SAME
conversation AND the SAME uploader, and fail hard (not partially) when any
requested id doesn't resolve.

Run from ``platform-api``: ``pytest -q tests/test_chat_attachment_authorization.py``.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.models.chat_attachment import ChatAttachment
from app.services.chat_attachment_adapter import (
    AttachmentAuthorizationError,
    build_attachment_context,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _enable_attachments(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "chat_attachments_v1_enabled", True)


def _attachment(**overrides) -> ChatAttachment:
    base = dict(
        tenant_id=1,
        conversation_id=10,
        uploaded_by=100,
        original_filename="report.pdf",
        safe_filename="report.pdf",
        mime_type="application/pdf",
        byte_size=1234,
        sha256="a" * 64,
        storage_key="k",
        status="ready",
        extraction_result={"document_text": "quarterly results"},
    )
    base.update(overrides)
    return ChatAttachment(**base)


async def test_returns_context_for_the_owning_conversation_and_uploader(db_session):
    att = _attachment()
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)

    ctx = await build_attachment_context(
        db_session, tenant_id=1, user_id=100, conversation_id=10, attachment_ids=[att.id]
    )
    assert ctx is not None
    assert "quarterly results" in ctx


async def test_raises_when_attachment_belongs_to_a_different_conversation(db_session):
    att = _attachment(conversation_id=10)
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)

    with pytest.raises(AttachmentAuthorizationError):
        await build_attachment_context(
            db_session, tenant_id=1, user_id=100, conversation_id=999, attachment_ids=[att.id]
        )


async def test_raises_when_attachment_belongs_to_a_different_uploader(db_session):
    att = _attachment(uploaded_by=100)
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)

    with pytest.raises(AttachmentAuthorizationError):
        await build_attachment_context(
            db_session, tenant_id=1, user_id=999, conversation_id=10, attachment_ids=[att.id]
        )


async def test_raises_on_a_guessed_id_that_does_not_exist(db_session):
    with pytest.raises(AttachmentAuthorizationError):
        await build_attachment_context(
            db_session, tenant_id=1, user_id=100, conversation_id=10, attachment_ids=[999999]
        )


async def test_partial_match_is_a_hard_failure_not_a_partial_include(db_session):
    """One authorized id plus one unauthorized id must fail entirely -- not
    silently return context built from only the authorized one."""
    att = _attachment()
    other = _attachment(id=None, conversation_id=999, uploaded_by=999)
    db_session.add_all([att, other])
    await db_session.commit()
    await db_session.refresh(att)
    await db_session.refresh(other)

    with pytest.raises(AttachmentAuthorizationError):
        await build_attachment_context(
            db_session,
            tenant_id=1,
            user_id=100,
            conversation_id=10,
            attachment_ids=[att.id, other.id],
        )


async def test_disabled_feature_flag_returns_none_without_querying(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "chat_attachments_v1_enabled", False)
    result = await build_attachment_context(
        db_session, tenant_id=1, user_id=100, conversation_id=10, attachment_ids=[1]
    )
    assert result is None


async def test_empty_attachment_ids_returns_none(db_session):
    result = await build_attachment_context(
        db_session, tenant_id=1, user_id=100, conversation_id=10, attachment_ids=[]
    )
    assert result is None
