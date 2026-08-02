# Devin-ready plan: land PR #120, then close out the operational follow-up

PR: https://github.com/lhoskins/tablescope-lh/pull/120
Branch: `claude/consolidate-demo-refresh-and-slot-fix` → `devin/r-echarts-e2e-validation`

## Why this PR exists

Three fixes had been verified working live for the simplicit tenant incident,
but only one of them (`145dadd`, the AI-retry fix / PR #119) was actually on
`devin/r-echarts-e2e-validation` — the branch the app is built from. The
other two were sitting on `devin/demo-company-refresh-existing-datasources`,
never merged:

- the 24-month calendar window fix (`2544060`)
- the Teiid reserved-keyword fix (`a728876`)
- the `/replace` sanitization-parity fix (`3701eb6`)
- the `--refresh-existing` demo-importer flag itself (`2616069`)

A fourth, newly-found bug is included too: `acquire_tenant_slot()`'s TTL was
refreshed on rejected attempts, so a leaked concurrency slot could never
expire once retries started hammering it (this is what stalled AI
reprocessing during the last simplicit refresh — the "reset the counter"
workaround was operational, not a code fix). That's `86510cc`, cherry-picked
into this branch with a regression test.

This PR's only job is to get all four onto the branch that's actually
deployed, so the next demo-installer run or `/replace` call can't silently
regress any of them again. It does not touch the simplicit tenant's live
data — that's the separate append-only refresh already staged in
`docs/simplicit-refresh-2026-08-02/` on `claude/validate-enhance-logic-r2fyy1`
(see `docs/devin-simplicit-24mo-append-refresh-validated-plan.md` there),
which is unrelated to this merge and should not be blocked on it.

## Steps

1. **Review PR #120.** Three files had genuine merge conflicts (both
   branches evolved them independently since the last shared ancestor); the
   PR description documents exactly how each was resolved and why. Worth a
   careful look:
   - `platform-api/app/routes/upload.py` — kept the newer `compare_schemas()`
     validation, grafted in the sanitization fix.
   - `platform-api/app/services/reference_library_processing.py` — kept the
     newer metadata-merge behavior and the `mark_project_insight_stale`
     import.
   - `ai-server/tablescope-ai-api/app/models/schemas.py` — trivial, comment
     only.
2. **Let CI run** (if configured for this repo) and confirm it's green.
   Locally, these all passed against the merged tree: `test_home_intel_tenant_slots.py`,
   `test_business_insight_shared_cache.py`, `test_reference_library.py`,
   `test_upload_intake.py`, `test_file_source_versions.py`,
   `scripts/tests/test_demo_company.py`, `scripts/tests/test_demo_importer.py`.
3. **Merge PR #120** into `devin/r-echarts-e2e-validation`.
4. **Whatever branch/commit currently backs the live app server should be
   moved onto this merged history** before the next demo-installer run —
   otherwise the same "which branch is actually deployed" ambiguity that
   caused this consolidation to be necessary in the first place will recur.

## Still open after this PR — do not consider the simplicit incident closed

This consolidation fixes the *code*. It does not resolve three things
that surfaced live and remain unexplained:

1. **The public AI endpoint was never reverted.** Per the earlier incident
   summary: `TABLESCOPE_AI_API_URL` was switched to the AI server's public IP
   (`32.186.54.52:8000`) and a public `8000` security-group rule was added,
   as a temporary diagnostic workaround. That workaround is still live.
   Revert to the private IP (`10.200.2.26:8000`), remove the public ingress
   rule, and confirm the cross-region VPC peering actually carries the
   insight-refresh traffic before calling this done — it was "in place but
   unconfirmed end-to-end" as of the last check.
2. **`TEIID31118 Element "i.DefectQty" is not defined by any relevant
   group"`** — a real AI SQL-generation error observed in the worker logs,
   distinct from the reserved-keyword issue this PR fixes. It self-repaired
   once via the `/ai/intelligence/fix-sql` retry path in the one instance
   observed, but that's a retry succeeding, not a root cause fixed. Worth
   watching for recurrence.
3. **The 6-month-vs-24-month display question is unresolved and separate
   from the data problem this PR and the sibling append-refresh plan fix.**
   No hardcoded 6-month lookback was found anywhere in `platform-api`,
   `ai-server`'s prompt code, or `web-ui`. Once the simplicit tenant's data
   genuinely has 24 months (via the append-refresh plan), if cards *still*
   show only ~6 months, that confirms the truncation is happening in how the
   AI plans/windows the trend query — not in data availability — and needs
   its own investigation.
