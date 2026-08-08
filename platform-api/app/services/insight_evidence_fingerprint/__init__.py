
from __future__ import annotations

from .canonicalization import EVIDENCE_FINGERPRINT_VERSION as EVIDENCE_FINGERPRINT_VERSION
from .canonicalization import EvidenceFingerprint as EvidenceFingerprint
from .canonicalization import _canonical_json as _canonical_json
from .canonicalization import _canonicalize_rows as _canonicalize_rows
from .canonicalization import _canonicalize_value as _canonicalize_value
from .canonicalization import _normalize_sql as _normalize_sql
from .canonicalization import _normalize_whitespace as _normalize_whitespace
from .canonicalization import _parse_aggregations_from_sql as _parse_aggregations_from_sql
from .canonicalization import _parse_columns_from_sql as _parse_columns_from_sql
from .canonicalization import _parse_tables_from_sql as _parse_tables_from_sql
from .canonicalization import _sha256 as _sha256
from .deduplication import are_evidence_duplicates as are_evidence_duplicates
from .deduplication import deduplicate_by_evidence as deduplicate_by_evidence
from .deduplication import merge_card_evidence as merge_card_evidence
from .deduplication import select_duplicate_winner as select_duplicate_winner
from .fingerprint_builders import build_evidence_fingerprint as build_evidence_fingerprint
from .fingerprint_builders import build_plan_fingerprint as build_plan_fingerprint
from .fingerprint_builders import build_result_fingerprint as build_result_fingerprint
from .fingerprint_builders import build_semantic_fingerprint as build_semantic_fingerprint
from .fingerprint_builders import build_series_fingerprint as build_series_fingerprint
from .fingerprint_builders import fingerprint_for_card as fingerprint_for_card

"""Canonical evidence fingerprints for generated insight cards.

Implements the four fingerprint families required by the evidence-first
insight pipeline:

* planFingerprint    - the analytical intent, source scope, and method
* resultFingerprint    - the canonicalized query result set
* seriesFingerprint    - the chartable series extracted from the result
* semanticFingerprint  - the semantic roles (dimensions, measures, period,
                         grain, filters) derived from the plan and result

Deduplication uses these fingerprints instead of title wording, so identical
evidence cannot surface as multiple cards merely because the LLM phrased the
title or summary differently.
"""
