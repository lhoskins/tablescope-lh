"""Reference Library service — shared helpers for tiers, permissions, scoping.

Used by the reference-library routes, the processing pipeline, the suggestion
engine and the bulk-import engine. Keeps tier/permission/scoping logic in one
place so it is enforced consistently at the data-access layer (not just the UI).
"""

from __future__ import annotations

import difflib
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role
from app.models.project import ProjectMember
from app.models.reference_library import (
    DOMAIN_TAGS,
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)

logger = logging.getLogger(__name__)

# Case-insensitive lookup of the canonical display domain tag.
_DOMAIN_LOOKUP = {d.lower(): d for d in DOMAIN_TAGS}
# A few common aliases seen in CSVs / the architecture doc.
_DOMAIN_ALIASES = {
    "supply chain": "Supply Chain & Procurement",
    "procurement": "Supply Chain & Procurement",
    "finance": "Finance & Accounting",
    "legal": "Legal & Compliance",
    "compliance": "Legal & Compliance",
    "cybersecurity": "IT & Cybersecurity",
    "it": "IT & Cybersecurity",
    "manufacturing": "Manufacturing & Quality",
    "quality": "Manufacturing & Quality",
    "engineering": "Engineering & Product",
    "product": "Engineering & Product",
    "marketing": "Marketing & Sales",
    "sales": "Marketing & Sales",
    "government": "Government & Defense",
    "defense": "Government & Defense",
}


def normalize_domain_tag(raw: str | None) -> tuple[str, bool]:
    """Return (canonical_domain, was_remapped).

    Unknown values map to ``"Other"`` with ``was_remapped=True`` so callers can
    surface a warning rather than hard-failing.
    """
    if not raw:
        return "Other", True
    key = raw.strip().lower()
    if key in _DOMAIN_LOOKUP:
        return _DOMAIN_LOOKUP[key], False
    if key in _DOMAIN_ALIASES:
        return _DOMAIN_ALIASES[key], False
    return "Other", True


def domain_storage_key(domain: str | None) -> str:
    """Filesystem-safe slug for a domain tag, used in storage paths."""
    if not domain:
        return "other"
    return "".join(c if c.isalnum() else "_" for c in domain.strip().lower()).strip("_")


# Case-insensitive regex matching known domain tags and common aliases.
# Longest aliases first so "supply chain" wins over "supply" / "chain".
_REFERENCE_DOMAIN_PATTERN: re.Pattern | None = None


def _build_reference_domain_pattern() -> re.Pattern:
    global _REFERENCE_DOMAIN_PATTERN
    if _REFERENCE_DOMAIN_PATTERN is None:
        candidates = set(_DOMAIN_ALIASES.keys()) | {d.lower() for d in DOMAIN_TAGS}
        ordered = sorted(candidates, key=len, reverse=True)
        _REFERENCE_DOMAIN_PATTERN = re.compile(
            r"\b(" + "|".join(re.escape(c) for c in ordered) + r")\b",
            re.IGNORECASE,
        )
    return _REFERENCE_DOMAIN_PATTERN


def extract_reference_domains(text: str | None) -> list[str]:
    """Return the canonical Reference Library domain tags mentioned in *text*.

    Recognizes both official ``DOMAIN_TAGS`` (e.g. ``IT & Cybersecurity``) and
    common aliases (``it`` -> ``IT & Cybersecurity``). The ``it`` alias is only
    treated as the IT domain when it appears as the acronym ``IT`` to avoid
    matching the common pronoun.
    """
    if not text:
        return []
    pattern = _build_reference_domain_pattern()
    seen: dict[str, None] = {}
    for match in pattern.finditer(text):
        matched = match.group(1)
        key = matched.strip().lower()
        canonical = _DOMAIN_ALIASES.get(key) or _DOMAIN_LOOKUP.get(key)
        if not canonical:
            continue
        # Avoid matching the pronoun "it"; require the IT acronym.
        if key == "it" and matched != "IT":
            continue
        if canonical not in seen:
            seen[canonical] = None
    return list(seen.keys())


# ── Permissions ──────────────────────────────────────────────────────────────


def can_write_industry(context: RequestContext) -> bool:
    """Industry-tier writes are platform-staff only (ROOT_ADMIN)."""
    return has_role(context.role, Role.ROOT_ADMIN)


def can_write_company(context: RequestContext) -> bool:
    """Company-tier writes require tenant admin (or platform staff)."""
    return has_role(context.role, Role.TENANT_ADMIN)


async def can_write_project(session: AsyncSession, context: RequestContext, project_id: int) -> bool:
    """Project-tier writes require project admin (or tenant/platform admin)."""
    if has_role(context.role, Role.TENANT_ADMIN):
        return True
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.user_id,
        )
    )
    if member is None:
        return False
    return has_role(member.role, Role.ADMIN)


async def can_write_tier(
    session: AsyncSession,
    context: RequestContext,
    tier: str,
    project_id: int | None,
) -> bool:
    if tier == TIER_INDUSTRY:
        return can_write_industry(context)
    if tier == TIER_COMPANY:
        return can_write_company(context)
    if tier == TIER_PROJECT:
        if project_id is None:
            return False
        return await can_write_project(session, context, project_id)
    return False


# ── Duplicate detection ──────────────────────────────────────────────────────


def _norm_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


async def find_duplicate_in_tier(
    session: AsyncSession,
    *,
    tier: str,
    title: str,
    tenant_id: int | None = None,
    project_id: int | None = None,
    threshold: float = 0.9,
) -> ReferenceDocument | None:
    """Fuzzy-match ``title`` against existing docs in the same tier/scope.

    Returns the best match above ``threshold`` (case-insensitive), else None.
    Used both for upload duplicate warnings and for the bulk-import
    "update existing stub vs create new" decision.
    """
    stmt = select(ReferenceDocument).where(ReferenceDocument.tier == tier)
    if tier == TIER_COMPANY:
        stmt = stmt.where(ReferenceDocument.tenant_id == tenant_id)
    elif tier == TIER_PROJECT:
        stmt = stmt.where(ReferenceDocument.project_id == project_id)
    candidates = (await session.scalars(stmt)).all()

    target = _norm_title(title)
    best: ReferenceDocument | None = None
    best_ratio = 0.0
    for cand in candidates:
        ratio = difflib.SequenceMatcher(None, target, _norm_title(cand.title)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = cand
    if best is not None and best_ratio >= threshold:
        return best
    return None


async def count_documents_by_tier(session: AsyncSession, tier: str) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(ReferenceDocument).where(ReferenceDocument.tier == tier))
        or 0
    )
