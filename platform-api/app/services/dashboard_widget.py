"""Shared helpers for saving dashboard widgets from AI-generated insight cards.

Keeps route handlers thin and guarantees that ``home_save_dashboard`` and the
new ``save-card-to-dashboard`` endpoint reuse the same SQL normalization,
saved-query reuse, chart-type mapping, and widget-config shape.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_query import SavedQuery
from app.routes.ai_proxy import (
    _detect_datasource,
    _map_chart_subtype,
    _map_chart_type,
)

_SQL_NORM_RE = re.compile(r"\s+")


def normalize_widget_sql(sql: str) -> str:
    """Collapse whitespace and strip trailing semicolons for equivalence."""
    return _SQL_NORM_RE.sub(" ", sql.strip().rstrip(";").lower())


async def find_or_create_saved_query(
    session: AsyncSession,
    *,
    project_id: int,
    title: str,
    sql: str,
    user_id: int,
    allowed_tables: list[str] | None = None,
    existing_by_sql: dict[str, SavedQuery] | None = None,
) -> SavedQuery:
    """Return a reusable ``SavedQuery`` for ``sql`` or create one.

    The optional ``existing_by_sql`` cache lets callers normalizing many widgets
    in one transaction avoid repeated DB round-trips.
    """
    sql_clean = sql.strip().rstrip(";")
    norm = normalize_widget_sql(sql_clean)

    if existing_by_sql is not None:
        existing = existing_by_sql.get(norm)
        if existing is not None:
            return existing

    rows = (
        await session.scalars(
            select(SavedQuery).where(
                SavedQuery.project_id == project_id,
                SavedQuery.is_archived.is_(False),
            )
        )
    ).all()
    by_norm = {
        normalize_widget_sql(q.sql_text): q
        for q in rows
        if q.sql_text
    }
    if existing_by_sql is not None:
        existing_by_sql.update(by_norm)

    if norm in by_norm:
        return by_norm[norm]

    query = SavedQuery(
        project_id=project_id,
        owner_id=user_id,
        name=title,
        description="",
        sql_text=sql_clean,
        left_datasource=_detect_datasource(sql_clean, allowed_tables or []),
        ai_generated=True,
    )
    session.add(query)
    await session.flush()
    if existing_by_sql is not None:
        existing_by_sql[norm] = query
    return query


def build_widget_config(
    *,
    title: str,
    query_id: int,
    chart_type: str,
    label_column: str | None = None,
    value_column: str | None = None,
    value_column_2: str | None = None,
    explanation: str = "",
    index: int = 0,
    widget_id: str | None = None,
) -> dict[str, Any]:
    """Build a dashboard widget config consistent with ``DashboardViewer``."""
    mapped_type = _map_chart_type(chart_type)
    default_w = {"kpi": 3, "table": 12, "pie": 4}.get(mapped_type, 6)
    default_h = {"kpi": 2, "table": 5}.get(mapped_type, 4)

    x_col = label_column or ""
    y_col = value_column or ""
    x_type: str | None = None
    y2_col: str | None = None

    if chart_type in ("scatter", "bubble"):
        # Two-metric charts: the two value columns become X and Y.
        x_col = value_column or x_col
        y_col = value_column_2 or value_column or ""
        x_type = "number"
    elif value_column_2:
        # Dual-axis / combo: primary Y is value, secondary Y is value2.
        y2_col = value_column_2

    widget: dict[str, Any] = {
        "id": widget_id or f"ai_widget_{index}",
        "title": title,
        "explanation": explanation,
        "type": mapped_type,
        "chartSubtype": _map_chart_subtype(chart_type),
        "dataSource": {"kind": "query", "queryId": query_id},
        "xColumn": x_col,
        "yColumn": y_col,
        "aggregation": "sum",
        "sortBy": "x_asc",
        "filters": [],
        "colSpan": default_w,
        "position": index,
        "gridX": (index % 2) * 6,
        "gridY": (index // 2) * default_h,
        "gridW": default_w,
        "gridH": default_h,
    }
    if x_type:
        widget["xColumnType"] = x_type
    if y2_col:
        widget["y2Column"] = y2_col
        widget["y2Aggregation"] = "sum"
    return widget
