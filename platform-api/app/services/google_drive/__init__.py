"""Google Drive Spreadsheet connector: OAuth + read-only file/tab/range discovery.

See ``docs`` (or the implementation plan handed to Devin) for the full
design. This package covers Workstreams B/C only: OAuth connection, file
listing, tab enumeration, and range preview. It does NOT create Teiid data
sources, detect multiple tables on one tab, or touch WildFly/Teiid config --
those are Workstreams D/E, explicitly deferred (see the plan's Increment 2
and the Devin handoff notes).
"""

from __future__ import annotations

from .client import SUPPORTED_MIME_TYPES, GoogleDriveClient, GoogleDriveError
from .oauth import (
    GoogleOAuthError,
    InvalidStateTokenError,
    build_authorization_url,
    create_state_token,
    exchange_code_for_tokens,
    is_configured,
    refresh_access_token,
    verify_state_token,
)

__all__ = [
    "SUPPORTED_MIME_TYPES",
    "GoogleDriveClient",
    "GoogleDriveError",
    "GoogleOAuthError",
    "InvalidStateTokenError",
    "build_authorization_url",
    "create_state_token",
    "exchange_code_for_tokens",
    "is_configured",
    "refresh_access_token",
    "verify_state_token",
]
