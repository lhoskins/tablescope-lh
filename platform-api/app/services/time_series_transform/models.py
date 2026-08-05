
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ZERO_TOLERANCE = Decimal("1E-9")


class TimeSeriesInterval(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class TimeSeriesRange(str, Enum):
    DAYS_7 = "7d"
    DAYS_30 = "30d"
    DAYS_90 = "90d"
    YEAR_1 = "1y"
    YEARS_2 = "2y"


class TimeSeriesMetric(BaseModel):
    name: str
    aggregation: str | None = None
    is_rate_or_ratio: bool = False
    value_format: str | None = None


class TimeSeriesPoint(BaseModel):
    label: str
    period_start: str
    period_end: str
    current_value: float | None = None
    previous_value: float | None = None
    percent_change_ratio: float | None = None
    percent_change_label: str | None = None
    comparison_status: str = "valid"
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class TimeSeriesCalculation(BaseModel):
    formula: str = "((current_value - previous_value) / previous_value) * 100"
    interval: str
    range: str
    range_start: str | None = None
    range_end: str | None = None
    as_of: str | None = None
    previous_periods_included: int = 0
    notes: list[str] = Field(default_factory=list)


class TimeSeriesResponse(BaseModel):
    insight_id: str
    metric: TimeSeriesMetric
    interval: str
    range: str
    timezone: str
    comparison_label: str
    points: list[TimeSeriesPoint]
    calculation: TimeSeriesCalculation
    warnings: list[str] = Field(default_factory=list)
    eligible: bool = True
    source_grain: str | None = None
    supported_intervals: list[str] = Field(default_factory=list)


class _ParsedPeriod:
    __slots__ = ("date", "grain", "raw")

    def __init__(self, d: date, grain: TimeSeriesInterval, raw: str) -> None:
        self.date = d
        self.grain = grain
        self.raw = raw


class _SourcePoint:
    __slots__ = ("date", "label", "value", "value2")

    def __init__(
        self,
        d: date,
        value: float | None,
        label: str,
        value2: float | None = None,
    ) -> None:
        self.date = d
        self.value = value
        self.label = label
        self.value2 = value2


def _supported_intervals(source_grain: TimeSeriesInterval) -> list[str]:
    order = [TimeSeriesInterval.DAY, TimeSeriesInterval.WEEK, TimeSeriesInterval.MONTH, TimeSeriesInterval.YEAR]
    idx = order.index(source_grain)
    return [i.value for i in order[idx:]]


def _interval_coarser_or_equal(
    source_grain: TimeSeriesInterval,
    target: TimeSeriesInterval,
) -> bool:
    order = {TimeSeriesInterval.DAY: 0, TimeSeriesInterval.WEEK: 1, TimeSeriesInterval.MONTH: 2, TimeSeriesInterval.YEAR: 3}
    return order[target] >= order[source_grain]
