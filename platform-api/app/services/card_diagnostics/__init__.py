
from __future__ import annotations

from .action_proposals import propose_actions as propose_actions
from .action_proposals import suggested_followups as suggested_followups
from .cross_reference_planning import CrossReference as CrossReference
from .cross_reference_planning import _mentions as _mentions
from .cross_reference_planning import _subject_terms as _subject_terms
from .cross_reference_planning import plan_cross_references as plan_cross_references
from .diagnostics_planning import _CHANGE_WORDS as _CHANGE_WORDS
from .diagnostics_planning import _THRESHOLD_WORDS as _THRESHOLD_WORDS
from .diagnostics_planning import OPPORTUNITY as OPPORTUNITY
from .diagnostics_planning import RISK as RISK
from .diagnostics_planning import STAGE_CORROBORATE as STAGE_CORROBORATE
from .diagnostics_planning import STAGE_EXPLAIN as STAGE_EXPLAIN
from .diagnostics_planning import STAGE_LOCALISE as STAGE_LOCALISE
from .diagnostics_planning import STAGE_PROJECT as STAGE_PROJECT
from .diagnostics_planning import STAGE_QUANTIFY as STAGE_QUANTIFY
from .diagnostics_planning import STAGE_VERIFY as STAGE_VERIFY
from .diagnostics_planning import STAGE_WHEN as STAGE_WHEN
from .diagnostics_planning import TREND as TREND
from .diagnostics_planning import ActionProposal as ActionProposal
from .diagnostics_planning import DiagnosticSpec as DiagnosticSpec
from .diagnostics_planning import _humanize as _humanize
from .diagnostics_planning import _infer_metric as _infer_metric
from .diagnostics_planning import card_family as card_family
from .diagnostics_planning import logger as logger
from .diagnostics_planning import period_comparison_triggers as period_comparison_triggers
from .diagnostics_planning import plan_card_diagnostics as plan_card_diagnostics
from .diagnostics_planning import should_compare_periods as should_compare_periods
from .envelope_extraction import _first_label as _first_label
from .envelope_extraction import _top_named as _top_named
from .envelope_extraction import extract_findings as extract_findings
from .envelope_extraction import extract_markers as extract_markers
from .group_evidence import GROUP_EVIDENCE_INTENTS as GROUP_EVIDENCE_INTENTS
from .group_evidence import describe_group_leader as describe_group_leader
from .group_evidence import summarise_group_evidence as summarise_group_evidence

"""Purpose-driven Deeper analysis: dissect a finding, then propose what to do.

Deeper analysis used to scan *tables* and offer whatever generic analyses the
shape allowed. Because a period comparison can be computed from almost any
dated measure, month-over-month and year-over-year dominated every project — the
section answered "what can we compute?" instead of "what should we do about
this?".

This module inverts that. Deeper analysis takes an existing **Risk, Trend or
Opportunity card** and works it like an analyst would:

1. **Localise** — which segment carries the problem? (a plant, a supplier, a
   region — the answer you can act on)
2. **Time-localise** — when did it start? A level shift dates the cause.
3. **Quantify** — how abnormal is it, and how large?
4. **Explain** — what moves with it, and which measures account for it?
5. **Project** — where does it end up if nobody intervenes?
6. **Corroborate** — does another data source or document say the same thing?
7. **Act** — propose mitigation (risk) or capture (opportunity), tied to the
   evidence above.

**Period comparisons are demoted to triggered evidence.** MoM/YoY only earns a
place when something warrants it — the card is about a change, a threshold was
breached, an anomaly or level shift was detected — so it supports a finding
rather than being the finding.

Pure and dependency-light: planning, trigger logic, action proposals and
follow-up questions are all unit-testable without a database, an LLM or R.
"""
