# Devin: merge + deploy — stop guessing a relative date filter with no profile data

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-sql-generation-no-profile-date-guess`
**Base:** `UX-design-03` (branched off it directly, since this fix's test
depends on the `ollama_url` → `llm_target_url` rename already merged there)

**1 commit · `ai-server/` only · no migration · no platform-api change · all tests green**

---

## 1. What this fixes

Same "What is the backup failure rate?" query as the two prior fixes, a
third occurrence, and a different root cause from both:

- Both prior defects (`TEIID31100` glued keywords, `TEIID30492` missing
  `FROM`) are confirmed fixed — the query now generates valid SQL and
  **executes successfully**.
- It returns **zero rows**. The generated SQL filters to the last 60 days
  from wall-clock `CURRENT_DATE` (2026-09-02), but `it_backup_jobs_CSV`'s
  actual data is from June 2026 — outside that window, so every row is
  filtered out. This is not an engine error; Teiid has nothing to reject.

**Root cause:** `it_backup_jobs_CSV` has no persisted `DataSourceAIProfile`
row — confirmed by checking `data_source_ai_profiles` for project 44, which
lists profiles for other sources (`biostats.csv`, `cities.csv`, etc.) but
not this one. Per `data_source_profiler.py`'s own docstring, this happens
when a source "predates this profiling, or the upload path failed to
profile it" — `DataSourceAIProfile` creation is wired into
`finalize_tabular_import` only (traced via `create_ai_profile`), so a
source uploaded before that code existed simply has no profile and none
gets backfilled automatically.

Without a profile, the AI catalog sent to the SQL generator has no
`"profile"` line for this source (see `data_source_profiler.py::profile_sources`
— it only emits a line when both an `AI profile` and `field profiles`
exist). The generator's own prompt (`_SEMANTIC_RULES` in `llm_client.py`)
already told the model what to do **when a profile line is present** ("last
30 days" etc. must respect the range the profile shows) — but said nothing
about what to do when there's **no** profile line at all. Left to its own
judgment, the model defaulted to a plausible-sounding "last 60 days"
wall-clock filter, which happened to exclude 100% of this source's actual
data.

**Not the same class of bug as the other two.** Those were malformed SQL
Teiid rejected outright; this is syntactically and semantically valid SQL
that simply encodes a wrong assumption about the data — Teiid has no way to
know that either, since "return zero rows" is a completely valid answer to
a completely valid filter.

---

## 2. What changed

`ai-server/tablescope-ai-api/app/services/llm_client.py`: one new bullet
added to `_SEMANTIC_RULES`, immediately after the existing "when a source
has a profile line" rule:

```diff
     "- When a source below has a 'profile' line, it tells you the row count "
     "and, for the date column, its real range. Before applying a relative "
     "date filter ('last 30 days', 'this quarter', 'year over year'), check "
     "that range: if 'now' or the requested window falls outside it, or the "
     "range covers less time than the requested window, do NOT add a filter "
     "that would exclude all the rows the profile shows exist — query the "
     "data as it is instead of a filter guessed from wall-clock time.\n"
+    "- When a source below has NO 'profile' line, its real date range is "
+    "unknown to you — you have no way to check it against a relative "
+    "filter. Do NOT apply a relative/wall-clock date filter ('last 30 "
+    "days', 'this quarter', 'year over year', etc.) in that case: query the "
+    "source's full date range (omit the date filter) unless the user's "
+    "request names an explicit date or range themselves. A wrong guess "
+    "here doesn't error — it silently returns zero rows instead of an "
+    "answer, which is worse than not filtering at all.\n"
 )
```

`_SEMANTIC_RULES` is always included in `generate_sql`'s system prompt
(static text, not conditional on any one source), so this rule reaches the
model for every request — it's the model's own job to apply it per-source
based on whether that source's catalog entry has a `profile:` line, exactly
like the existing profile-present rule already works.

**Why the prompt, not the repair loop:** this never reaches `repair_sql` —
the query executes without an engine error, so the repair agent (which only
runs after a Teiid-rejected query) is never invoked. The only place to fix
a wrong-but-valid SQL query is at generation time.

**Why the general fix over a one-off data patch:** `it_backup_jobs_CSV` is
not the only source that can lack a profile — any pre-profiling-era upload
has the same gap. Backfilling one profile row would only fix this one
source and leave the same failure mode live for every other one. There is
also no supported code path to do a backfill today (`create_ai_profile` is
only ever called from `finalize_tabular_import`, i.e. at upload time) — a
real backfill/reprofile feature would be a separate, larger piece of work,
not something to improvise as a one-off DB write from here.

---

## 3. Verification

| Suite | Result |
|---|---|
| `ai-server` `ruff check` (touched files) | clean |
| New tests (`test_semantic_rules_no_profile_guidance.py`) | 2 / 2 passed |
| Full `ai-server` `pytest` | 158 / 158 passed |

```bash
cd ai-server/tablescope-ai-api
pytest -q tests/test_semantic_rules_no_profile_guidance.py
pytest -q
ruff check app/services/llm_client.py tests/test_semantic_rules_no_profile_guidance.py
```

(`mypy` was not run cleanly here — this sandbox's mypy invocation is
missing `pydantic`/`httpx`/`fastapi` stubs for the whole `ai-server`
codebase, confirmed pre-existing/environment-wide by running it against an
untouched file (`app/routers/ai_ask.py`), not something this change
introduced.)

---

## 4. Deploy

`ai-server` only, prompt-text change, no schema/migration, no platform-api
change.

```bash
docker compose build ai-api
docker compose up -d ai-api
```

### Rollback
```bash
git revert 6a87c499
docker compose build ai-api
docker compose up -d ai-api
```

---

## 5. Verify live

- Re-run "What is the backup failure rate?" against `it_backup_jobs_CSV`
  and confirm it now returns actual rows/an answer instead of "the live
  query result does not include any data values."
- Spot-check one or two other sources that DO have a profile (e.g. any
  source uploaded recently) with a relative-date question ("revenue last 30
  days") to confirm the existing profile-present behavior is unaffected —
  this change only adds a new rule for the no-profile case, it doesn't
  touch the existing one.
- If other pre-profiling-era sources exist and get asked relative-date
  questions, this same fix should prevent the same zero-rows-without-error
  failure for them too — worth spot-checking if any come to mind.

---

## 6. Report back

Confirmation the reported query now returns real data; whether any other
un-profiled source surfaces the same pattern (expected to be fixed by this
same change, but worth confirming); and whether a real "backfill/reprofile
an existing source" feature is worth scoping as separate follow-up work —
it wasn't in scope here since no code path for it exists today.
