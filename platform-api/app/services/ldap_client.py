"""LDAP directory client for test, preview, and synchronization."""

from __future__ import annotations

import logging
import ssl
import tempfile
from typing import Any

from app.models.ldap_connection import LdapConnection
from app.services.enterprise_auth import decrypt_ldap_bind_secret

logger = logging.getLogger(__name__)


def _ca_file_from_config(conn: LdapConnection) -> str | None:
    if not conn.ca_certificate:
        return None
    # ldap3 requires a file path for CA certs. Write a temp file and rely on
    # the OS to clean it up (it is not sensitive by itself).
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as fh:
        fh.write(conn.ca_certificate)
        return fh.name


def _build_tls(conn: LdapConnection) -> Any:
    try:
        from ldap3 import Tls
    except ImportError as exc:  # pragma: no cover - dependency check
        raise RuntimeError("ldap3 is not installed") from exc

    ca_file = _ca_file_from_config(conn)
    validate = ssl.CERT_REQUIRED if conn.require_cert_validation else ssl.CERT_NONE
    if ca_file:
        return Tls(validate=validate, ca_certs_file=ca_file)
    return Tls(validate=validate)


def _build_server(conn: LdapConnection) -> Any:
    from ldap3 import Server

    tls = _build_tls(conn) if conn.protocol == "ldaps" or conn.use_starttls else None
    use_ssl = conn.protocol == "ldaps"
    return Server(
        conn.host,
        port=conn.port,
        use_ssl=use_ssl,
        tls=tls,
        connect_timeout=conn.connect_timeout,
    )


async def test_ldap_connection(conn: LdapConnection) -> dict[str, Any]:
    """Validate LDAPS/StartTLS connectivity and bind credentials.

    Returns a safe dict with ``success`` and ``message``; never includes secrets.
    """
    from ldap3 import AUTO_BIND_NO_TLS, Connection

    bind_password = decrypt_ldap_bind_secret(conn.bind_secret_encrypted) or ""
    if conn.bind_dn and not bind_password:
        return {"success": False, "status": "error", "message": "Bind DN provided but no password is stored."}

    try:
        server = _build_server(conn)
        if conn.use_starttls:
            c = Connection(
                server,
                user=conn.bind_dn,
                password=bind_password,
                auto_bind=AUTO_BIND_NO_TLS,
                read_only=True,
                receive_timeout=conn.connect_timeout,
            )
            if not c.bind():
                return {"success": False, "status": "error", "message": "LDAP bind failed (invalid credentials or bind DN)."}
            if not c.start_tls():
                return {"success": False, "status": "error", "message": "LDAP StartTLS failed."}
        else:
            c = Connection(
                server,
                user=conn.bind_dn,
                password=bind_password,
                auto_bind=True,
                read_only=True,
                receive_timeout=conn.connect_timeout,
            )
        # Light validation search at the base DN.
        base = conn.base_dn or ""
        if not c.search(base, "(objectClass=*)", search_scope="BASE", attributes=["dn"]):
            return {"success": False, "status": "error", "message": "Could not read the configured base DN."}
        c.unbind()
        return {"success": True, "status": "success", "message": "Connection and bind succeeded."}
    except Exception as exc:
        logger.exception("LDAP test failed for tenant %s host %s", conn.tenant_id, conn.host)
        return {"success": False, "status": "error", "message": f"LDAP connection failed: {exc}"}


def _normalize_dn(base: str, relative: str | None) -> str:
    if not relative:
        return base
    relative = relative.strip()
    if relative.startswith("dn:") or "=" in relative:
        return relative
    # Treat as a relative path under base_dn (comma-separated).
    base = base.rstrip(",")
    relative = relative.lstrip(",")
    return f"{relative},{base}" if base else relative


def _guid_from_attrs(attrs: dict[str, Any]) -> str | None:
    for key in ("objectGUID", "objectGuid", "objectguid"):
        val = attrs.get(key)
        if val:
            if isinstance(val, list):
                val = val[0]
            if isinstance(val, bytes):
                return val.hex()
            return str(val)
    return None


def _sid_from_attrs(attrs: dict[str, Any]) -> str | None:
    for key in ("objectSid", "objectSid", "objectsid"):
        val = attrs.get(key)
        if val:
            if isinstance(val, list):
                val = val[0]
            if isinstance(val, bytes):
                return val.hex()
            return str(val)
    return None


def _first_attr(attrs: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        val = attrs.get(key)
        if val:
            if isinstance(val, list):
                val = val[0]
            return str(val)
    return None


async def preview_ldap_directory(
    conn: LdapConnection,
    *,
    max_users: int = 50,
    max_groups: int = 50,
) -> dict[str, Any]:
    """Return a preview of users and groups from the directory.

    Does not write anything. Results are limited and stripped of secrets.
    """
    from ldap3 import SUBTREE, Connection

    bind_password = decrypt_ldap_bind_secret(conn.bind_secret_encrypted) or ""
    try:
        server = _build_server(conn)
        c = Connection(
            server,
            user=conn.bind_dn,
            password=bind_password,
            auto_bind=True,
            read_only=True,
            receive_timeout=conn.connect_timeout,
        )

        user_filter = conn.user_filter or "(objectClass=user)"
        group_filter = conn.group_filter or "(objectCategory=group)"
        user_base = _normalize_dn(conn.base_dn, conn.user_search_base)
        group_base = _normalize_dn(conn.base_dn, conn.group_search_base)

        users = []
        if c.search(user_base, user_filter, search_scope=SUBTREE, attributes=["objectGUID", "objectSid", "userPrincipalName", "mail", "displayName", "userAccountControl"], size_limit=max_users):
            for entry in c.entries:
                attrs = entry.entry_attributes_as_dict
                users.append({
                    "directory_object_guid": _guid_from_attrs(attrs),
                    "directory_object_sid": _sid_from_attrs(attrs),
                    "upn": _first_attr(attrs, "userPrincipalName"),
                    "email": _first_attr(attrs, "mail"),
                    "display_name": _first_attr(attrs, "displayName"),
                    "enabled": not bool(int(_first_attr(attrs, "userAccountControl") or "0") & 0x2),
                })

        groups = []
        if c.search(group_base, group_filter, search_scope=SUBTREE, attributes=["objectGUID", "objectSid", "cn", "name", "displayName"], size_limit=max_groups):
            for entry in c.entries:
                attrs = entry.entry_attributes_as_dict
                groups.append({
                    "directory_object_guid": _guid_from_attrs(attrs),
                    "directory_object_sid": _sid_from_attrs(attrs),
                    "name": _first_attr(attrs, "cn", "name", "displayName"),
                })

        c.unbind()
        return {"users": users, "groups": groups, "membership_count": 0}
    except Exception as exc:
        logger.exception("LDAP preview failed for tenant %s host %s", conn.tenant_id, conn.host)
        raise RuntimeError(f"LDAP preview failed: {exc}") from exc
