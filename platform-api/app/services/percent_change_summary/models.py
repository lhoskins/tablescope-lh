
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ZERO_TOLERANCE = Decimal("1E-9")


class SummarySort(BaseModel):
    field: str = "latest_absolute_change"
    direction: str = "desc"


class PercentChangeSummaryRequest(BaseModel):
    project_ids: list[int] = []
    interval: str = "month"
    range: str = "1y"
    search: str | None = None
    sort: SummarySort | None = None
    cursor: str | None = None
    page_size: int = 25


class SummaryPeriod(BaseModel):
    key: str
    label: str
    start: str
    end: str
    is_latest: bool = False


class SummaryCell(BaseModel):
    current_value: float | None = None
    previous_value: float | None = None
    percent_change_ratio: float | None = None
    status: str = "unavailable"  # display status: positive | negative | zero | unavailable
    comparison_status: str = "unavailable"
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class SummaryStatistics(BaseModel):
    latest: float | None = None
    min: float | None = None
    max: float | None = None
    median: float | None = None
    average: float | None = None
    standard_deviation: float | None = None
    cumulative_change: float | None = None
    valid_count: int = 0


class SummaryRow(BaseModel):
    insight_id: str
    title: str
    project_id: int
    project_name: str
    project_color: str | None = None
    priority_score: float | None = None
    source_grain: str | None = None
    supported_intervals: list[str] = Field(default_factory=list)
    data_through: str | None = None
    cells: dict[str, SummaryCell] = Field(default_factory=dict)
    statistics: SummaryStatistics = Field(default_factory=SummaryStatistics)


class PercentChangeSummaryPage(BaseModel):
    page_size: int
    total_in_scope: int
    total_eligible: int
    total_excluded: int
    next_cursor: str | None = None


class PercentChangeSummaryResponse(BaseModel):
    schema_version: int = 1
    interval: str
    range: str
    as_of: str
    comparison_label: str
    periods: list[SummaryPeriod]
    rows: list[SummaryRow]
    interval_support_counts: dict[str, int]
    page: PercentChangeSummaryPage
    excluded_by_reason: dict[str, int]
    warnings: list[str] = Field(default_factory=list)


def _coerce_project_id(value: Any) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _insight_id(card: dict[str, Any]) -> str:
    return str(card.get("insightId") or card.get("id") or "")
