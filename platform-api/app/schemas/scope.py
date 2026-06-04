"""Scope (drill-down) schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Leading digit allowed: digit-leading file views are valid scope targets.
_IDENT_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_$.]*$"


class ScopeCreate(BaseModel):
    sourceTable: str = Field(pattern=_IDENT_PATTERN)
    sourceColumn: str = Field(pattern=_IDENT_PATTERN)
    targetTable: str = Field(pattern=_IDENT_PATTERN)
    targetColumn: str = Field(pattern=_IDENT_PATTERN)


class ScopeUpdate(BaseModel):
    targetTable: str = Field(pattern=_IDENT_PATTERN)
    targetColumn: str = Field(pattern=_IDENT_PATTERN)


class ScopeRead(BaseModel):
    name: str
    sourceTable: str
    sourceColumn: str
    targetTable: str
    targetColumn: str
    tenantId: int | None = None
