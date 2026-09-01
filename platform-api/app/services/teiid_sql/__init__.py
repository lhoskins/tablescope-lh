
from __future__ import annotations

from .identifiers import _AGGREGATE_NAMES as _AGGREGATE_NAMES
from .identifiers import _TEIID_RESERVED_ALIASES as _TEIID_RESERVED_ALIASES
from .identifiers import _is_aggregate_expression as _is_aggregate_expression
from .identifiers import _next_clause_position as _next_clause_position
from .identifiers import _strip_output_alias as _strip_output_alias
from .identifiers import add_missing_from_clause as add_missing_from_clause
from .identifiers import collapse_bare_following_parens as collapse_bare_following_parens
from .identifiers import normalize_teiid_identifiers as normalize_teiid_identifiers
from .identifiers import rebuild_group_by_from_select as rebuild_group_by_from_select
from .string_filters import _fix_string_literal_columns as _fix_string_literal_columns
from .string_filters import _split_top_level as _split_top_level
from .string_filters import normalize_teiid_string_filters as normalize_teiid_string_filters
from .string_filters import project_table_schema as project_table_schema
from .timestamps import _CAST_COLUMN_RE as _CAST_COLUMN_RE
from .timestamps import _CAST_LITERAL_RE as _CAST_LITERAL_RE
from .timestamps import _DATE_TYPES as _DATE_TYPES
from .timestamps import _LITERAL_MASKS as _LITERAL_MASKS
from .timestamps import _PSQL_MASK_RE as _PSQL_MASK_RE
from .timestamps import _PSQL_MASK_TOKENS as _PSQL_MASK_TOKENS
from .timestamps import _SLASH_DATE_RE as _SLASH_DATE_RE
from .timestamps import _STRING_RE as _STRING_RE
from .timestamps import _TO_DATE_RE as _TO_DATE_RE
from .timestamps import _TO_TIMESTAMP_RE as _TO_TIMESTAMP_RE
from .timestamps import _build_re as _build_re
from .timestamps import _cleanup_stray_string_literals as _cleanup_stray_string_literals
from .timestamps import _extract_string as _extract_string
from .timestamps import _mask_for_literal as _mask_for_literal
from .timestamps import _mask_or_cast_for_column as _mask_or_cast_for_column
from .timestamps import _normalize_existing_parse_calls as _normalize_existing_parse_calls
from .timestamps import _translate_psql_mask as _translate_psql_mask
from .timestamps import date_mask_for_value as date_mask_for_value
from .timestamps import date_masks_from_samples as date_masks_from_samples
from .timestamps import normalize_date_casts as normalize_date_casts
from .timestamps import normalize_teiid_timestamps as normalize_teiid_timestamps

"""Teiid-specific SQL normalizations for generated query previews.

The AI planner emits SQL that is closer to PostgreSQL/ANSI than to Teiid. The
most common failure mode is timestamp/date parsing: `to_timestamp(...)`,
`CAST('literal' AS timestamp)`, and `CAST("col" AS timestamp)` against a
string column all fail when the literal/column does not match Teiid's default
cast format. This module rewrites those expressions to Teiid's
`PARSETIMESTAMP` / `PARSEDATE` with the right SimpleDateFormat mask.

It is intentionally not a full SQL transpiler — only the timestamp/date
patterns that the preview execution path actually sees are handled here.
"""
