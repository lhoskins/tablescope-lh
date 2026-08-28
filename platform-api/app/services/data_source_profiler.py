"""Render AI grounding summaries from existing upload-time data profiles.

The AI's SQL generator and "why" investigation planner previously saw only a
source's name and column list -- never how much data it actually holds, what
date range it spans, or what values a categorical column takes. That let the
model invent columns that do not exist, apply relative date filters ("last 60
days") the data cannot possibly satisfy, and reason about a "rising trend"
over a single month of data.

Rather than computing a fresh profile (another Teiid round trip on the ask
path -- the exact kind of latency this bug started from), this reads the
per-field profile every tabular upload already computes and persists at
finalize time (``finalize_tabular_import`` -> ``create_ai_profile``, from a
full scan of the uploaded file): ``DataSourceFieldProfile.row_count`` isn't
there, but ``distinct_count``, ``sample_values``, ``min_value``/``max_value``
per field are exactly what's needed, and ``DataSourceAIProfile.row_count`` has
the total. No new query against the tenant's data plane is added at all.

A source with no persisted profile (predates this profiling, or the upload
path failed to profile it) simply has no summary here -- this only adds
grounding, never blocks or fails catalog building.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source_ai_profile import DataSourceAIProfile, DataSourceFieldProfile
from app.models.file_source_meta import FileSourceMeta

logger = logging.getLogger(__name__)

_MAX_CATEGORICAL_COLUMNS = 5
_MAX_CATEGORICAL_VALUES = 12
_DATE_TYPES = {"date", "timestamp"}


def _pick_date_column(columns: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the date-like column using the PHYSICAL (Teiid) type, not the
    file-profiler's content-sniffed type -- a CSV/file column is stored as a
    string in Teiid no matter how date-like its values look, and that
    distinction is exactly what the SQL generator needs (FORMATDATE vs.
    PARSETIMESTAMP + FORMATTIMESTAMP)."""
    for c in columns:
        if str(c.get("type") or "").lower() in _DATE_TYPES:
            return c
    for c in columns:
        name = str(c.get("name") or "")
        if re.search(r"date|timestamp", name, re.IGNORECASE):
            return c
    return None


def _pick_categorical_columns(
    columns: list[dict[str, Any]], date_column_name: str | None
) -> list[str]:
    picked: list[str] = []
    for c in columns:
        name = str(c.get("name") or "")
        if not name or name == date_column_name:
            continue
        col_type = str(c.get("type") or "string").lower()
        if col_type not in ("string", ""):
            continue
        if name.lower().endswith("id"):
            continue
        if re.search(r"guid|uuid|url|email|note|description|comment|address|phone", name, re.IGNORECASE):
            continue
        picked.append(name)
        if len(picked) >= _MAX_CATEGORICAL_COLUMNS:
            break
    return picked


async def profile_sources(
    session: AsyncSession, sources: list[FileSourceMeta]
) -> dict[str, str]:
    """Return ``{view_name: profile_summary}`` from each source's persisted
    upload-time field profile, e.g. ``"40 rows; \"Date\" range 2026-06-13 to
    2026-06-24 (text); \"System\" values: ERP, FileServer, MES, PLM"``.
    """
    profiles: dict[str, str] = {}
    ds_ids = [ds.id for ds in sources if ds.id is not None]
    if not ds_ids:
        return profiles

    # Latest AI profile per data source (row_count) -- a source can have been
    # re-profiled, so keep only the highest-id row per data_source_id.
    ai_profile_rows = (
        await session.scalars(
            select(DataSourceAIProfile)
            .where(DataSourceAIProfile.data_source_id.in_(ds_ids))
            .order_by(DataSourceAIProfile.id.asc())
        )
    ).all()
    latest_profile_by_ds: dict[int, DataSourceAIProfile] = {}
    for p in ai_profile_rows:
        latest_profile_by_ds[p.data_source_id] = p  # later (higher id) wins
    if not latest_profile_by_ds:
        return profiles

    latest_profile_ids = [p.id for p in latest_profile_by_ds.values()]
    field_rows = (
        await session.scalars(
            select(DataSourceFieldProfile).where(
                DataSourceFieldProfile.profile_id.in_(latest_profile_ids)
            )
        )
    ).all()
    fields_by_ds: dict[int, dict[str, DataSourceFieldProfile]] = {}
    for f in field_rows:
        fields_by_ds.setdefault(f.data_source_id, {})[f.field_name] = f

    for ds in sources:
        if ds.id is None or not ds.view_name:
            continue
        ai_profile = latest_profile_by_ds.get(ds.id)
        field_profiles = fields_by_ds.get(ds.id) or {}
        if ai_profile is None or not field_profiles:
            continue

        columns = [
            c for c in (ds.column_types or []) if isinstance(c, dict) and c.get("name")
        ]
        if not columns:
            continue

        parts: list[str] = []
        if ai_profile.row_count is not None:
            parts.append(f"{ai_profile.row_count} rows")

        date_col = _pick_date_column(columns)
        if date_col and date_col.get("name"):
            date_name = str(date_col["name"])
            fp = field_profiles.get(date_name)
            if fp and fp.min_value is not None and fp.max_value is not None:
                date_type = str(date_col.get("type") or "").lower()
                type_label = date_type if date_type in _DATE_TYPES else "text"
                parts.append(
                    f'"{date_name}" range {fp.min_value} to {fp.max_value} ({type_label})'
                )

        for col_name in _pick_categorical_columns(
            columns, date_col.get("name") if date_col else None
        ):
            fp = field_profiles.get(col_name)
            if not fp or not fp.sample_values:
                continue
            if fp.distinct_count is not None and fp.distinct_count > _MAX_CATEGORICAL_VALUES:
                # Not really categorical (or the sample undercounts it) -- a
                # partial value list would mislead more than it grounds.
                continue
            values = sorted({str(v) for v in fp.sample_values if v not in (None, "")})
            if not values:
                continue
            parts.append(f'"{col_name}" values: {", ".join(values)}')

        if parts:
            profiles[ds.view_name] = "; ".join(parts)

    return profiles
