# Devin: merge + deploy — fix cross-project leak in project_workspace conversations

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-project-workspace-cross-project-leak`
**Base:** `UX-design-03`

**1 commit · `platform-api/` only · no migration · no ai-server change · all tests green**

---

## 1. What this fixes

Live report: opening the AI Assistant from inside the **Sales** project (the
"Workspace — Sales" thread) and asking "Show my top performers" returned an
answer built entirely from a **completely unrelated project's data** — a
movies/ratings dataset (`Title`, `Score`, `Year_col` — titles like "Taxi
Driver", "Goodfellas"), nothing to do with Sales. Separately, in an IT
context, the AI Assistant surfaced "Existing Insight" cards
(`Top performers by ResolutionHours`, `SiteID`/`DaysLost`) that were
generated for a **different project entirely**, screenshotted with the
annotation "Related to IT. Should not be shown in Sales Scope" (twice).

This is not a minor UX issue — the assistant answered a Sales question with
literally unrelated data and presented it as if it were the Sales answer,
with no indication anything was off.

## Root cause

`app/services/conversational_analytics/__init__.py::execute_turn()` has a
per-turn gate:

```python
is_project_scoped = conversation.surface == "project_insights"
```

used for two things:

1. **Whether to re-resolve which project a turn belongs to.** When
   `is_project_scoped` is `False`, every turn calls
   `resolve_business_insight_project()` — a semantic, question-text-based
   resolver — and can swap `project_id` to whatever project it scores
   highest, with **no anchor at all on a conversation's first turn**
   (`anchor_project_id=conversation.project_id if prior_turn is not None else
   None`). Once resolved, the wrong project gets **committed onto
   `conversation.project_id`** (`if resolved_project_id is not None:
   conversation.project_id = resolved_project_id`), poisoning every
   subsequent turn in the same thread, not just the one that triggered it.
2. **`allow_cross_project` for insight-card matching**
   (`conversation.surface != "project_insights"`) — whether cached insight
   cards from *other* projects the user can access are eligible to be
   recommended under the answer.

The bug: `project_workspace` — the surface `canonical_conversations.py`
actually creates for "Workspace — `<project>`" threads (confirmed directly:
`title = f"Workspace — {project.name}"`, and its `canonical_scope_key()`
**requires** a `project_id` and keys the conversation per-project, exactly
like `project_insights`) — was never included in either check. It fell
through to the cross-project behavior meant only for the genuinely
untethered `ai_assistant`/`business_insights` surfaces, even though its own
contract (and an existing, unrelated test,
`test_project_workspace_active_resource_from_another_project_is_ignored`)
already establishes it's supposed to stay pinned to one project for its
whole lifetime.

`business_insights` (the one surface genuinely meant to search across a
user's accessible projects — confirmed against a stale-but-informative
prior planning doc, `docs/devin-ai-assistant-cross-project-deep-analysis-plan.md`
on branch `claude/ai-assistant-cross-project-plan`, which independently
describes cross-project answering as an intentional, wanted capability for
the untethered ask surfaces) is unaffected by this fix — it isn't in either
condition's project-scoped set, so its existing cross-project search keeps
working exactly as before.

## 2. What changed

`platform-api/app/services/conversational_analytics/__init__.py`:

```diff
-    is_project_scoped = conversation.surface == "project_insights"
+    is_project_scoped = conversation.surface in ("project_insights", "project_workspace")
     ...
-            allow_cross_project=conversation.surface != "project_insights",
+            allow_cross_project=not is_project_scoped,
```

The second line now reuses the same `is_project_scoped` computed above
instead of its own separate, narrower string comparison — so there's one
source of truth for "is this surface pinned to one project," not two
checks that can drift apart again the same way this bug happened in the
first place.

## 3. Tests added

`platform-api/tests/test_canonical_conversations.py`, both **verified to
fail against the pre-fix code and pass with the fix** (confirmed by
temporarily reverting the fix and re-running):

- **`test_project_workspace_never_re_resolves_to_another_project`** — mocks
  `resolve_business_insight_project` to confidently return a different,
  unrelated project; asserts the resolver is never even called
  (`calls == []`) and the turn's `project_id` stays the workspace's own
  project. This is the test that directly reproduces the "movies data under
  Sales" failure mode.
- **`test_project_workspace_never_widens_insight_cards_to_another_project`**
  — spies on `insight_card_match._cards_for_projects` (not the LLM
  selector) and asserts it's only ever called for the workspace's own
  project. Note: the sibling `test_project_insights_never_widens_to_another_project`
  test mocks the LLM selector and a `"generation_error"` response — that
  pattern doesn't actually work for this new test, because `execute_turn`
  returns early on any non-`"success"` status, **before** ever reaching the
  insight-matching block at all, and the real call site passes
  `use_llm=False` so the LLM selector is never invoked regardless. This new
  test instead uses the default *successful* live-query mock (which scores
  low relevance against "Show my top performers" via `_live_query_score`'s
  term-overlap check, which is what actually reaches the matching block)
  and spies one level lower, at the actual project-list-gating call.

## 4. Verification

| Suite | Result |
|---|---|
| `ruff check` (touched files) | clean |
| `mypy` (touched file) | clean |
| `test_canonical_conversations.py` | 12 / 12 passed (10 existing + 2 new) |
| `test_conversational_analytics.py`, `test_ai_ask_and_run.py`, `test_project_recent_conversations.py`, `test_business_insight_project_resolver.py` (regression) | 80 / 80 passed |

```bash
cd platform-api
pytest -q tests/test_canonical_conversations.py tests/test_conversational_analytics.py tests/test_ai_ask_and_run.py tests/test_project_recent_conversations.py tests/test_business_insight_project_resolver.py
ruff check app/services/conversational_analytics/__init__.py tests/test_canonical_conversations.py
mypy app/services/conversational_analytics/__init__.py
```

## 5. Deploy

`platform-api` only, no migration, no ai-server change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

### Rollback
```bash
git revert c5488f01
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## 6. Verify live

- Open the AI Assistant from inside a specific project ("Workspace —
  `<project>`") and ask a generic question with no explicit project name
  (the exact failure trigger — "Show my top performers" had none). Confirm
  the answer comes from that project's own data, not a different one.
- Ask a second, follow-up question in the same thread referencing a term
  more strongly associated with a *different* project you also have access
  to (e.g. "IT" if you're in a "Sales" workspace). Confirm it does **not**
  switch projects mid-conversation — `project_workspace` should now be as
  immovable as `project_insights` already was.
- Confirm no "Existing Insight" card from a different project appears under
  a `project_workspace` answer.
- Confirm `business_insights` (the tenant-wide ask surface, not tied to any
  one project) is unaffected — cross-project search/insight-widening should
  still work there exactly as before.

## 7. Report back

Confirmation the reported scenario ("Show my top performers" from inside
Sales) now answers from Sales data; confirmation no other-project insight
cards appear in a `project_workspace` conversation; and whether any
existing `project_workspace` conversations already have a corrupted
`conversation.project_id` from before this fix (the "committed onto
`conversation.project_id`" poisoning described in §1 would persist on
already-affected threads even after this deploy — worth a quick DB check:
`SELECT id, project_id, canonical_key FROM analytics_conversations WHERE
surface = 'project_workspace'` and spot-verify `project_id` matches what
`canonical_key`'s `project_workspace:<id>` suffix says it should be. A
mismatch there would need a manual data fix, not a code fix, since this
change only stops the corruption going forward.)
