"""Regression tests for identifier validation.

A file named like ``0_revenueTest.csv`` produces the Teiid view name
``0_revenueTest_CSV``, which starts with a digit. These names are valid views
(the servlet emits them as quoted identifiers) and must pass the platform-api
identifier guards, which always wrap the name in double quotes when building
SQL.
"""

from __future__ import annotations

import re

import pytest

from app.routes.query import _IDENTIFIER_RE as QUERY_RE
from app.routes.query_scopes import _FIELD_RE
from app.schemas.scope import _IDENT_PATTERN
from app.services.query_executor import _IDENTIFIER_RE as EXECUTOR_RE


@pytest.mark.parametrize(
    "name",
    [
        "0_revenueTest_CSV",
        "9Sales_XLSX",
        "RevenueTest_CSV",
        "_hidden",
        "schema.table",
    ],
)
def test_valid_identifiers_accepted(name: str) -> None:
    assert QUERY_RE.match(name)
    assert EXECUTOR_RE.match(name)
    assert re.match(_IDENT_PATTERN, name)
    assert _FIELD_RE.match(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        'bad"name',
        "bad;drop",
        "bad-name",
        "with space",  # space not allowed for table identifiers
    ],
)
def test_invalid_identifiers_rejected(name: str) -> None:
    assert not QUERY_RE.match(name)
    assert not EXECUTOR_RE.match(name)
    assert not re.match(_IDENT_PATTERN, name)
