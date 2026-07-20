# AI Assistant Chart Reformatting — Refactor (Before / After)

## Why this refactor

The previous fix made phrases like *"run this query using horizontal bar format"* work by
**adding more regexes**. That approach can never be consistent:

- Every new phrasing ("flip it sideways", "present that as a ring chart", "can you do the
  donut version?") needs a new hardcoded pattern.
- The regex tables decided the *result* of the request (which chart type, which subtype) at
  code-authoring time — exactly the "hardcoded determination" that kept breaking.
- The parsing logic ran twice (once to classify, once inside `apply_chart_change`), and the
  chart vocabulary was duplicated in three private functions.

The refactor moves the decision to the LLM and keeps the platform as a **deterministic
validator**:

```
user message ──► AI server /ai/intelligence/conversation-turn  (LLM, JSON-only, temp 0)
                    │  intent + structured chart patch
                    ▼
platform-api  apply_chart_patch()   ◄── validates against the renderer's closed chart
                    │                   vocabulary + the REAL columns of the cached result
                    ▼
             chart_config persisted on the turn ──► web-ui WidgetRenderer
```

Nothing about the user's *phrasing* is hardcoded anymore. The only fixed data left is the
**closed vocabulary of chart types/subtypes the frontend renderer can actually draw** — that
is grounding (the model must choose from what is renderable), not intent determination.

A deliberately tiny fallback remains for degraded mode only (AI server disabled or
unreachable), so the feature never hard-fails.

---

## Blacked-out (removed) code

All of the following was deleted from
`platform-api/app/services/conversational_analytics.py` (~170 lines):

| Removed | What it was |
|---|---|
| `_CHART_CHANGE_SIGNALS` (20 regex tuples) | Hardcoded phrasings → chart actions |
| `_QUERY_CHANGE_SIGNALS` (6 regexes) | Hardcoded phrasings → query change |
| `_EXPLAIN_SIGNALS` (3 regexes) | Hardcoded phrasings → explain |
| `classify_conversational_intent()` | Regex-first classifier |
| `_match_chart_change()` | 40-line regex → params dispatcher |
| `_map_chart_type()` / `_map_chart_style()` | Duplicated chart vocabulary |
| `_matches_any()` | Regex helper |
| `apply_chart_change()` | Re-ran the regexes a second time to build the config |

## Added

| Added | Where | What it does |
|---|---|---|
| `POST /ai/intelligence/conversation-turn` | `ai-server/.../routers/ai.py` | LLM classifies the turn from grounded state; strict-JSON output; deterministic sanitizer |
| `ConversationTurnClassifyRequest/Response` | `ai-server/.../models/schemas.py` | Typed contract for the endpoint |
| `classify_conversation_turn()` | `platform-api/.../ai_intelligence_client.py` | Signed client call, returns `None` when AI is disabled |
| `classify_turn()` (async, LLM-first) | `platform-api/.../conversational_analytics.py` | Sends message + grounded state; falls back only when AI is off |
| `apply_chart_patch()` | same | Applies a **structured** patch; validates chart types/subtypes and real result columns |
| `_fallback_classify()` + 2 small regexes | same | Degraded mode only |
| "change it to a donut chart" chip | `web-ui/.../project-conversation-screen.tsx` | Discoverability |
| 4 new tests | `platform-api/tests/test_conversational_analytics.py` | LLM path, fallback path, column grounding, stale-subtype reset |

---

## Before

### 1. Intent classification (regex tables — removed)

```python
# Deterministic chart-only signals. More specific patterns first.
_CHART_CHANGE_SIGNALS = [
    (r"\b(?:run|show|display|plot|graph|chart|reformat)\s+(?:this|it|the\s+(?:query|chart|result|data))?(?:\s+(?:query|chart|result|data))?\s*(?:using|as|in|with)\s+(?:a\s+)?(horizontal\s+bar|stacked\s+bar|grouped\s+bar|bar|line|pie|table|scatter|donut|area)(?:\s+(?:chart|format|graph|view))?\b", "chart_type"),
    (r"\bchange\s+(?:it|this|the chart)\s+(?:to|into|as)\s+(?:a\s+)?(horizontal\s+bar|stacked\s+bar|grouped\s+bar|bar|line|pie|table|scatter|donut|area)(?:\s+(?:chart|format|graph|view))?\b", "chart_type"),
    (r"\bmake\s+(?:it|this)\s+(?:a\s+)?(horizontal\s+bar|stacked\s+bar|grouped\s+bar|bar|line|pie|table|scatter|donut|area)(?:\s+(?:chart|format|graph|view))?\b", "chart_type"),
    (r"\bshow\s+(?:it|this)\s+as\s+(?:a\s+)?(horizontal\s+bar|stacked\s+bar|grouped\s+bar|bar|line|pie|table|scatter|donut|area)(?:\s+(?:chart|format|graph|view))?\b", "chart_type"),
    (r"\b(use|make)\s+(\w+)\s+(?:the\s+)?x[- ]?axis\b", "label_column"),
    # ... 15 more patterns ...
]

_QUERY_CHANGE_SIGNALS = [
    r"\b(filter|only|just|exclude|remove|where)\b",
    r"\b(compare|compare to|versus|vs|year over year|yoy|month over month)\b",
    # ...
]

_EXPLAIN_SIGNALS = [
    r"\b(how did you|how do you|how was this|why|explain|show me|tell me)\s+(?:calculate|compute|derive|get|come up with|this|the sql|sql)\b",
    # ...
]


def classify_conversational_intent(question, prior_turn):
    q = _normalize_question(question)
    chart_match, chart_params = _match_chart_change(q)
    if chart_match and prior_turn and prior_turn.result_cache:
        return ConversationalIntent.CHART_CHANGE, chart_params
    if _matches_any(q, _EXPLAIN_SIGNALS):
        return ConversationalIntent.EXPLAIN, {}
    if prior_turn is None:
        return ConversationalIntent.NEW_ANALYSIS, {}
    if _matches_any(q, _QUERY_CHANGE_SIGNALS):
        return ConversationalIntent.QUERY_CHANGE, {}
    return ConversationalIntent.QUERY_CHANGE, {}
```

### 2. Chart change application (re-ran the regexes — removed)

```python
def apply_chart_change(chart_config, result, instruction):
    chart_match, params = _match_chart_change(_normalize_question(instruction))
    if not chart_match:
        return chart_config, "I couldn't understand that chart change."
    # ... 60 lines of param-by-param mutation + a hardcoded mapping of
    # "horizontal bar" -> subtype, "donut" -> pie, etc., duplicated from
    # _map_chart_type()/_map_chart_style() ...
```

**Problems:** any phrasing not matching a regex fell through to `query_change` and re-ran
SQL (or errored); "donut" mapped to plain `pie` (the ring never rendered); chart vocabulary
lived in three places; instructions were parsed twice.

---

## After

### 1. LLM-first classification, grounded in the real conversation state

`platform-api/app/services/conversational_analytics.py`:

```python
async def classify_turn(question, prior_turn, *, tenant_id, user_id, project_id):
    """Classify a turn LLM-first; degrade deterministically when AI is off."""
    state = _prior_turn_state(prior_turn)   # real columns, prior SQL, current chart
    if ai_intelligence_client.is_enabled():
        try:
            decision = await ai_intelligence_client.classify_conversation_turn(
                tenant_id=tenant_id, user_id=user_id, project_id=project_id,
                message=question, **state,
            )
        except AIUnavailableError as exc:
            logger.warning("Conversation-turn classifier unavailable: %s", exc)
            decision = None
        if decision:
            intent = decision.get("intent")
            if intent in {...valid intents...}:
                chart = decision.get("chart") or {}
                return intent, chart if intent == CHART_CHANGE else {}
    return _fallback_classify(question, prior_turn)
```

The classifier receives the **grounded state** — not just the message:

```python
def _prior_turn_state(prior_turn):
    return {
        "has_prior_result": True,
        "prior_sql": prior_turn.sql or "",
        "result_columns": cache.get("columns", []),
        "numeric_columns": profile.get("numericColumns", []),
        "categorical_columns": profile.get("categoricalColumns", []),
        "row_count": cache.get("rowCount", 0),
        "current_chart": prior_turn.chart_config or {},
    }
```

### 2. The AI server endpoint (`ai-server/.../routers/ai.py`)

```python
@router.post("/intelligence/conversation-turn",
             response_model=ConversationTurnClassifyResponse)
async def classify_conversation_turn(req):
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    raw = await llm_client.generate(
        prompt=_conversation_turn_prompt(req),        # grounded state + rules + examples
        system_prompt=_CONVERSATION_TURN_SYSTEM_PROMPT,
        model=settings.reasoning_model,
        temperature=0.0,                              # classification: deterministic
        max_tokens=400,
        response_format="json",                       # constrained JSON decoding
    )
    parsed = _parse_json_response(raw or "") or {}

    intent = str(parsed.get("intent") or "").strip().lower()
    if intent not in _CONVERSATION_INTENTS:
        intent = "query_change" if req.has_prior_result else "new_analysis"
    if intent in {"chart_change", "explain"} and not req.has_prior_result:
        intent = "new_analysis"

    chart = _sanitize_chart_patch(parsed.get("chart"), req.result_columns) \
        if intent == "chart_change" else {}
    if intent == "chart_change" and not chart:
        intent = "clarification"
    ...
```

The prompt gives the model a **closed chart vocabulary** (exactly what the web-ui
`WidgetRenderer` draws), the *decision rule* instead of phrase lists, and few-shot examples:

> Torn between `query_change` and `chart_change`? Ask: can the request be satisfied by
> re-drawing the **same rows and columns**? If yes it is `chart_change`; if it needs
> different rows, columns, filters, or aggregation it is `query_change`.

So *any* phrasing works — "flip it sideways", "ring style", "make those bars lie down" —
because the model reasons about meaning; the platform only checks that the output is legal.

### 3. Deterministic patch application (validation, not parsing)

```python
def apply_chart_patch(chart_config, result, patch):
    """The patch comes from the LLM classifier (or the degraded fallback); this
    function is the deterministic guardrail: every field is validated against
    the renderer's chart vocabulary and the columns that actually exist in the
    cached result, so the chart is always drawable and always grounded."""
    new_config = dict(chart_config)
    columns = (result.get("columns") or []) if result else []

    type_changed = patch.get("type") in _CHART_TYPES
    if type_changed:
        new_config["type"] = patch["type"]
        new_config.pop("subtype", None)   # "vertical bar" clears horizontal_bar
    subtype = patch.get("subtype")
    if subtype and subtype in _CHART_SUBTYPES.get(new_config.get("type", ""), set()):
        new_config["subtype"] = subtype

    label = patch.get("labelColumn")
    if label and label not in columns:
        return chart_config, (f"Column '{label}' is not in this result. "
                              f"Available columns: {', '.join(columns)}.")
    # ... valueColumns, sort, dataLabels, legend, title — same pattern ...
```

`donut` now round-trips correctly: the model emits `{"type": "pie", "subtype": "donut"}`,
the platform stores it, and the frontend (`chart_config.subtype` → `chartStyle` →
`chartSubtype`) renders an actual donut via the dashboard chart registry.

### 4. Degraded mode (the only regexes left — 2 of them)

```python
# Degraded-mode fallback (AI server disabled or unreachable ONLY).
_FALLBACK_CHART_CONTEXT = re.compile(
    r"\b(chart|graph|plot|format|visuali[sz]e|...|convert|run)\b")
_FALLBACK_EXPLAIN = re.compile(
    r"\b(explain|why|how did you|...|what sql)\b")

def _fallback_classify(question, prior_turn):
    """Minimal deterministic classifier for degraded mode (AI off/unreachable)."""
    ...
```

---

## AI prompting best practices now applied (and worth keeping)

These are the patterns the new endpoint uses; apply them to every LLM call in the product:

1. **One job per call.** The classifier only classifies and patches — it never writes SQL.
   Small, single-responsibility prompts are dramatically more consistent than one mega-prompt.
2. **Ground the model in real state.** The prompt contains the actual result columns,
   numeric/categorical split, prior SQL, and the currently rendered chart config. The model
   is told it may only reference columns from that list — that is what makes answers
   "grounded" rather than plausible.
3. **Closed vocabularies.** Chart types/subtypes are enumerated from what the renderer
   supports. The model chooses *within* the vocabulary; it never invents a format.
4. **Structured output, enforced twice.** `response_format="json"` constrains decoding at
   the model, and `_sanitize_chart_patch()` + `apply_chart_patch()` validate afterwards.
   Trust, but verify — the LLM proposes, deterministic code disposes.
5. **Temperature 0 for classification/SQL, higher only for prose.** Decisions should be
   reproducible; creativity belongs in narrative interpretation only.
6. **Decision rules + few-shot examples instead of phrase lists.** Give the model the
   *criterion* ("same rows re-drawn? → chart_change") and 4–6 examples covering the
   ambiguous edge cases. Examples are the highest-leverage prompt real estate.
7. **Confidence + reason for observability.** Every decision returns a one-sentence reason
   that is logged, so misclassifications can be diagnosed from logs instead of guessed at.
8. **Graceful degradation, never silent failure.** AI disabled → tiny deterministic
   fallback; AI errored → logged warning + fallback; model emitted an empty patch →
   honest `clarification` response instead of a wrong guess.

## Verification

- `platform-api`: `pytest tests/test_conversational_analytics.py` — **10 passed**
  (6 pre-existing + 4 new: LLM-driven donut change, degraded-mode horizontal bar,
  column grounding rejection, stale-subtype reset).
- `ai-server`: `pytest tests` — **39 passed**.
- `web-ui`: `npm run typecheck` and `npm run lint` — clean (one pre-existing unrelated
  warning).
- `ruff check` on all touched Python files — clean.
