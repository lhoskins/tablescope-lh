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


# ── Sliding session renewal ─────────────────────────────────────────────────
#
# Sessions were a hard 60 minutes with no refresh path: the first request after
# the hour 401'd and the client bounced to login, logging people out mid-task.


def _token(minutes_old: int, ttl: int = 60, **extra) -> str:
    """A token issued `minutes_old` minutes ago with a `ttl`-minute lifetime."""
    return _mint(int(time.time()) - minutes_old * 60, ttl, **extra)


def _mint(iat: int, ttl_minutes: int, **extra) -> str:
    from jose import jwt as _jwt

    from app.config import get_settings

    s = get_settings()
    payload = {
        "sub": "u", "tenant_id": 1, "org_id": 1, "user_id": 1,
        "role": "viewer", "permissions": [],
        "iss": s.jwt_issuer, "aud": s.jwt_audience,
        "iat": iat, "exp": iat + ttl_minutes * 60,
    }
    payload.update(extra)
    return _jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def test_a_fresh_token_is_not_renewed() -> None:
    """Renewal must stay off the hot path for most requests."""
    from app.auth.jwt import renew_access_token

    assert renew_access_token(_token(minutes_old=5)) is None


def test_a_token_past_halfway_is_renewed() -> None:
    from app.auth.jwt import renew_access_token

    renewed = renew_access_token(_token(minutes_old=45))
    assert renewed is not None
    claims = decode_access_token(renewed)
    assert claims.exp is not None and claims.exp > int(time.time()) + 3000


def test_renewal_preserves_the_two_factor_level() -> None:
    """Re-minting without `aal` would silently downgrade a verified session."""
    from app.auth.jwt import renew_access_token

    renewed = renew_access_token(_token(minutes_old=45, aal="aal2"))
    assert renewed is not None
    assert decode_access_token(renewed).aal == "aal2"


def test_renewal_preserves_identity_and_permissions() -> None:
    from app.auth.jwt import renew_access_token

    renewed = renew_access_token(
        _mint(int(time.time()) - 45 * 60, 60, sub="user-abc", tenant_id=42,
              user_id=7, role="admin", permissions=["scopes:write"])
    )
    claims = decode_access_token(renewed or "")
    assert (claims.sub, claims.tenant_id, claims.user_id) == ("user-abc", 42, 7)
    assert claims.role == "admin"
    assert claims.permissions == ["scopes:write"]


def test_the_session_start_is_carried_forward() -> None:
    """Otherwise each renewal resets the clock and the cap never applies."""
    from app.auth.jwt import renew_access_token

    started = int(time.time()) - 45 * 60
    first = renew_access_token(_mint(started, 60))
    assert first is not None
    assert decode_access_token(first).ses == started

    # A second renewal, an hour later, must keep the ORIGINAL session start.
    second = renew_access_token(_mint(int(time.time()) - 45 * 60, 60, ses=started))
    assert second is not None
    assert decode_access_token(second).ses == started


def test_activity_cannot_extend_a_session_past_the_absolute_cap() -> None:
    """The security boundary: sliding sessions still end."""
    from app.auth.jwt import renew_access_token
    from app.config import get_settings

    cap = get_settings().jwt_session_absolute_ttl_minutes
    old_start = int(time.time()) - (cap + 1) * 60
    assert renew_access_token(_mint(int(time.time()) - 45 * 60, 60, ses=old_start)) is None


def test_a_legacy_token_without_a_session_start_is_capped_from_its_issue_time() -> None:
    """Pre-existing tokens must not become renewable forever."""
    from app.auth.jwt import renew_access_token
    from app.config import get_settings

    cap = get_settings().jwt_session_absolute_ttl_minutes
    ancient = int(time.time()) - (cap + 1) * 60
    # Long-lived so it is still valid but issued before the cap window.
    assert renew_access_token(_mint(ancient, (cap + 120))) is None


def test_a_tampered_or_unparsable_token_is_never_renewed() -> None:
    from app.auth.jwt import renew_access_token

    assert renew_access_token("not-a-token") is None
    assert renew_access_token(_token(minutes_old=45) + "x") is None


def test_an_expired_token_is_not_renewed() -> None:
    """Renewal follows activity on a LIVE session; it cannot resurrect a dead one."""
    from app.auth.jwt import renew_access_token

    assert renew_access_token(_mint(int(time.time()) - 120 * 60, 60)) is None
