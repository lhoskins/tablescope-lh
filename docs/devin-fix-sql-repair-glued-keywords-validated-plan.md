# Devin: merge + deploy — fix TEIID31100 from glued SQL keywords

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-sql-repair-glued-keywords`
**Base:** `release/deploy-2026-08-07`

**1 commit · 2 files (`platform-api/` only) · no migration · no ai-server/WAR changes · all tests green**

---

## 1. What this fixes

Live incident: "What is the backup failure rate?" against `it_backup_jobs_CSV` failed repeatedly. The generated SQL had `...AS double) ENDORDER BY JobMonth` — a `CASE...END` expression's `END` landed with **zero whitespace** before `ORDER BY`, so Teiid's tokenizer read `ENDORDER` as one unrecognized identifier instead of two valid keywords (`TEIID31100 "Encountered ... ENDORDER ..."`).

Traced through the whole SQL-prep pipeline (`_prepare_sql`, `_cast_timestampdiff`, `_auto_cast_aggregates`) to confirm neither of those introduces it — they only ever insert characters around an existing span, never remove whitespace — so it's the model's own raw formatting reaching Teiid unguarded.

**Not a VDB-warm or restart issue.** The VDB warm-timeout / "connection closed" log lines seen alongside this were Teiid rejecting the same malformed SQL repeatedly and the connection pool reacting to that — downstream noise, not the cause. Restarting Teiid would not have fixed it: the next occurrence of this pattern would fail identically against a freshly warmed VDB.

---

## 2. What changed

`platform-api/app/routes/query_sql_helpers.py`: a new `_fix_glued_keywords` pass runs first inside `_prepare_sql`, inserting the missing space whenever `END` is glued directly to `ORDER BY`/`GROUP BY`/`WHERE`/`HAVING`/`LIMIT`.

**Why this closes it for every repair round, not just the first attempt:** `_prepare_sql` is the `normalize` callback `sql_repair_agent.run_repair_loop` calls at the top of every loop iteration (`current = await normalize(current)`), for both the initial query and every AI-repaired rewrite. That's also why the reported incident showed two `repair-sql-step` calls in a row that each still failed: the loop kept re-normalizing and re-executing the same glued-keyword pattern without ever fixing the actual defect.

---

## 3. Verification

| Suite | Result |
|---|---|
| `platform-api` `ruff check` | clean |
| `platform-api` `mypy` | clean |
| New tests (`test_fix_glued_keywords.py`) | 5 / 5 passed |
| `test_auto_cast_aggregates.py` (regression) | 14 / 14 passed |
| Targeted regression (`test_query_sql_repair.py`, `test_query_sql_helpers_retry.py`, `test_query_datasource_global_filters.py`, `test_query_datasource_authorization.py`) | 18 / 18 passed |

```bash
cd platform-api && pytest -q tests/test_fix_glued_keywords.py tests/test_auto_cast_aggregates.py && ruff check app tests && mypy app
```

---

## 4. Deploy

Frontend-untouched, no migration, no ai-server/WAR change — `platform-api` only.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

### Rollback
```bash
git checkout <previous-sha> -- platform-api/app/routes/query_sql_helpers.py
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

---

## 5. Verify live

- Re-run the reported query ("What is the backup failure rate?" / anything grouping by a computed month bucket with an `ORDER BY`) against `it_backup_jobs_CSV` and confirm it returns a result instead of repeatedly hitting `repair-sql-step`.
- Check the platform-api logs for the same conversation/turn shape as the incident: confirm no `TEIID31100`/`ENDORDER` pattern recurs.
- This fix is general (any `CASE...END` query hitting the same generation quirk on any source), so also spot-check one or two other existing grouped/ordered queries to confirm no regression in normal (already-correctly-spaced) SQL — `_fix_glued_keywords` is a no-op on those by design (see `test_leaves_correctly_spaced_sql_unchanged`).

---

## 6. Report back

Confirmation the reported query now succeeds; `pytest`/`ruff`/`mypy` totals in your own environment; and whether the VDB-warm-timeout/connection-closed log lines stop recurring now that Teiid is no longer being handed malformed SQL repeatedly (they should — but if they persist independent of this fix, that's a separate, real infra issue worth its own investigation, not something this change addresses).
