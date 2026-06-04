"""Grid preference schemas (per-user column order + hidden columns)."""

from __future__ import annotations

from pydantic import BaseModel


class GridPreferenceWrite(BaseModel):
    column_order: list[str] = []
    hidden_columns: list[str] = []


class GridPreferenceRead(BaseModel):
    id: int
    query_id: int
    column_order: list[str]
    hidden_columns: list[str]
