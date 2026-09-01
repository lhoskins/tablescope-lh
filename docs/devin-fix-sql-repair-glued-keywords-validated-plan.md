# Devin: merge + deploy — SQL-repair fixes for the "backup failure rate" incident

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-sql-repair-glued-keywords`
**Base:** `release/deploy-2026-08-07`

**3 commits · `platform-api/` only · no migration · no ai-server/WAR changes · all tests green**

This branch now covers **two distinct SQL-generation defects**, both hit by the
same "What is the backup failure rate?" query against `it_backup_jobs_CSV`, on
two separate occasions. They are unrelated at the root-cause level — see §1 —
so this doc walks through each separately, then verifies/deploys them together
since they live in the same branch and files.

---

## 1. What this fixes

### 1a. `TEIID31100` — glued `END`/`ORDER BY` keywords (fixed first)

The generated SQL had `...AS double) ENDORDER BY JobMonth` — a `CASE...END`
expression's `END` landed with **zero whitespace** before `ORDER BY`, so
Teiid's tokenizer read `ENDORDER` as one unrecognized identifier instead of
two valid keywords (`TEIID31100 "Encountered ... ENDORDER ..."`).

Traced through the whole SQL-prep pipeline (`_prepare_sql`,
`_cast_timestampdiff`, `_auto_cast_aggregates`) to confirm neither of those
introduces it — they only ever insert characters around an existing span,
never remove whitespace — so it's the model's own raw formatting reaching
Teiid unguarded.

**Not a VDB-warm or restart issue.** The VDB warm-timeout / "connection
closed" log lines seen alongside this were Teiid rejecting the same
malformed SQL repeatedly and the connection pool reacting to that —
downstream noise, not the cause.

### 1b. `TEIID30492` — missing `FROM` clause on aggregate queries (fixed second, separate incident report)

After 1a and the sibling `fix-vllm-ollama-gpu-contention` branch were both
identified, the *same* query was asked again (`conversation=224, turn=469`)
and failed differently: the generated SQL had aggregates
(`SUM(CASE WHEN LOWER(Result) = 'failed' ...)`, `COUNT(*)`) but **no `FROM`
clause at all** —

```
TEIID30492 Aggregate functions are only allowed HAVING/SELECT/ORDER BY clauses.
[SUM(...), COUNT(*)]
Both require a FROM clause to be present.
```

The AI server's `repair-sql-step` was called twice against this exact error
and neither rewrite added the missing `FROM` — this is a real SQL-generation
defect on the model side, not something the deterministic pipeline was
introducing.

**Root-caused a second, compounding bug while investigating**:
`query_sql_helpers.py`'s `_is_source_or_schema_error()` — the function that
tells `run_repair_loop` an error is unfixable and to give up without calling
the repair agent — matched the bare `TEIID30492` code as always-unfixable.
That code is **overloaded**: Teiid reuses it for two unrelated messages —
the genuine "source capabilities not loaded yet" condition this list exists
to catch (already matched separately by its own text, `"Capabilities for
... were not available"`, independent of the numeric code) — and this
completely different, rewrite-fixable "missing FROM clause" error. Matching
the bare code meant the **saved-query/dashboard path** (which passes
`is_unfixable_error=_is_source_or_schema_error`) would have skipped the
repair agent outright for this error, on top of the repair agent's own
rewrites not reliably fixing it anyway.

Note: this is genuinely a *different* defect from 1a, not something the
`ENDORDER` fix already covered — an AI-relayed diagnosis suggested merging
this branch alone would resolve it, which undersold the gap: the FROM-clause
omission needed its own fix (§2b), separate from the glued-keyword fix.

---

## 2. What changed

### 2a. Glued-keyword fix

`platform-api/app/routes/query_sql_helpers.py`: a new `_fix_glued_keywords`
pass runs first inside `_prepare_sql`, inserting the missing space whenever
`END` is glued directly to `ORDER BY`/`GROUP BY`/`WHERE`/`HAVING`/`LIMIT`.

### 2b. Missing-FROM-clause fix

- **`platform-api/app/services/teiid_sql/identifiers.py`**: new
  `add_missing_from_clause(sql, table_schema)`. Deterministically inserts
  `FROM "<table>"` right before the first trailing clause
  (`WHERE`/`GROUP BY`/`HAVING`/`ORDER BY`/`LIMIT`/`OFFSET`, or at the end if
  none) — but **only when exactly one table is in scope**. With more than
  one candidate table, guessing which one belongs in `FROM` risks silently
  returning the wrong table's data instead of surfacing an error the repair
  agent (or the user) can act on, so it's left alone in that case. Reuses
  the existing paren/quote-aware `_top_level_keyword_index` helper so it
  isn't fooled by a nested `FROM` inside e.g. `EXTRACT(QUARTER FROM "Month")`.
  Exported through `teiid_sql/__init__.py`.
- Wired into **both** normalize pipelines that hit Teiid, since the
  defect can surface on either path:
  - `platform-api/app/routes/ai_proxy_ask_and_run.py`'s `_normalize()` (chat
    ask-and-run path — this is the one the live incident actually went
    through).
  - `platform-api/app/routes/query_sql_helpers.py`'s `_prepare_sql()`
    (saved-query/dashboard execution path).
- `platform-api/app/routes/query_sql_helpers.py`'s `_is_source_or_schema_error()`:
  removed the bare `r"TEIID30492"` pattern from the unfixable-error list (see
  §1b for why); the genuine capabilities-not-loaded case stays caught by its
  own text pattern.

**Why both fixes close it for every repair round, not just the first
attempt:** the two normalize callbacks above (`_prepare_sql` /
`ai_proxy_ask_and_run._normalize`) are what `sql_repair_agent.run_repair_loop`
calls at the top of *every* loop iteration (`current = await
normalize(current)`), for both the initial query and every AI-repaired
rewrite. That's also why the incident reports showed repeated
`repair-sql-step` calls that each still failed: the loop kept
re-normalizing and re-executing the same defect without a deterministic fix
in place.

---

## 3. Verification

| Suite | Result |
|---|---|
| `platform-api` `ruff check` (touched files) | clean |
| `platform-api` `mypy` (touched files) | clean, no issues |
| `test_fix_glued_keywords.py` | 5 / 5 passed |
| `test_teiid_sql.py` (incl. 5 new `add_missing_from_clause` tests) | 47 / 47 passed |
| `test_sql_repair_agent.py` | passed |
| `test_auto_cast_aggregates.py` | 14 / 14 passed |
| `test_ai_ask_and_run.py`, `test_conversational_analytics.py`, `test_visualization_engine.py`, `test_canonical_conversations.py` | 103 / 103 passed |
| Targeted regression (`test_query_sql_repair.py`, `test_query_sql_helpers_retry.py`, `test_query_datasource_global_filters.py`, `test_query_datasource_authorization.py`) | 18 / 18 passed |

```bash
cd platform-api
pytest -q tests/test_fix_glued_keywords.py tests/test_teiid_sql.py tests/test_sql_repair_agent.py tests/test_auto_cast_aggregates.py
ruff check app tests
mypy app/services/teiid_sql/identifiers.py app/routes/ai_proxy_ask_and_run.py app/routes/query_sql_helpers.py
```

---

## 4. Deploy

Frontend-untouched, no migration, no ai-server/WAR change — `platform-api`
only.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

### Rollback
```bash
git revert <this-branch's-commits>
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

---

## 5. Verify live

- Re-run "What is the backup failure rate?" (or anything grouping by a
  computed month bucket with an `ORDER BY`, or a simple single-table
  aggregate) against `it_backup_jobs_CSV` and confirm it returns a result
  instead of repeatedly hitting `repair-sql-step`.
- Check platform-api logs for the same conversation/turn shape as either
  incident: confirm no `TEIID31100`/`ENDORDER` and no `TEIID30492`/missing-
  `FROM` pattern recurs.
- Both fixes are general (not specific to `it_backup_jobs_CSV`), so also
  spot-check one or two other existing grouped/ordered/aggregate queries to
  confirm no regression in normal, already-correct SQL — both new passes are
  no-ops on well-formed queries by design (see
  `test_leaves_correctly_spaced_sql_unchanged` and
  `test_add_missing_from_clause_leaves_existing_from_unchanged`).
- This branch depends on the AI stack actually being healthy to test against
  — deploy alongside (or after) the sibling `fix-vllm-ollama-gpu-contention`
  branch if that hasn't already gone out.

---

## 6. Report back

Confirmation the reported query now succeeds on both failure shapes;
`pytest`/`ruff`/`mypy` totals in your own environment; and whether the
missing-FROM defect recurs on any *other* query shape not covered by the
"exactly one table in scope" guard (multi-table queries missing `FROM` are
deliberately left unfixed here rather than guessed at — if that turns out to
be a live gap, it needs its own follow-up, not a silent guess at which table
was meant).
