"""JWT issuance + validation tests."""

from __future__ import annotations

import time

import pytest

from app.auth.jwt import AuthError, create_access_token, decode_access_token


def test_round_trip_token_carries_claims() -> None:
    token = create_access_token(
        sub="user-abc",
        tenant_id=42,
        user_id=7,
        role="editor",
        permissions=["scopes:write"],
    )
    claims = decode_access_token(token)
    assert claims.sub == "user-abc"
    assert claims.tenant_id == 42
    assert claims.user_id == 7
    assert claims.role == "editor"
    assert claims.permissions == ["scopes:write"]
    assert claims.org_id == 42  # redash-compat alias


def test_decoding_rejects_tampered_token() -> None:
    token = create_access_token(sub="u", tenant_id=1, user_id=1)
    # Replace multiple characters in the signature to guarantee invalidity
    parts = token.rsplit(".", 1)
    sig = parts[1]
    flipped = "".join(
        ("A" if c != "A" else "B") for c in sig[:8]
    ) + sig[8:]
    tampered = parts[0] + "." + flipped
    with pytest.raises(AuthError):
        decode_access_token(tampered)


def test_expired_token_is_rejected() -> None:
    token = create_access_token(
        sub="u", tenant_id=1, user_id=1, expires_minutes=-1
    )
    time.sleep(0.05)
    with pytest.raises(AuthError):
        decode_access_token(token)
