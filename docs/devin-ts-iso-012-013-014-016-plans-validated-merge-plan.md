# Devin: merge + deploy — four standalone security implementation plans (TS-ISO-012, 013, 014, 016)

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`

This is a **documentation-only merge**. Each of the four branches below adds exactly one plan file under `docs/security/` plus one follow-up commit (added during this validation pass) that appends a "Validation addendum" section to that same file. No application code, tests, or configuration changes are included in any of the four branches — nothing in this doc requires a runtime deploy, migration, or restart.

| Plan | Branch | Original commit | With validation addendum |
|---|---|---|---|
| TS-ISO-012 — Data-Plane Fallback Completion | `codex/ts-iso-012-data-plane-fallback-completion` | `54ed09ae1958eafa4edfc16b57b7ee74e459f08f` | `55b6f8a416722c988126328229429f798e28733c` |
| TS-ISO-013 — Session-Token Hardening | `codex/ts-iso-013-session-token-hardening` | `b68c50bc481af8d10e081448949e6102de9edf2a` | `5b8fd39b69d787f65a705586ddf9da5d722ba6cc` |
| TS-ISO-014 — Service Identity Scoping | `codex/ts-iso-014-service-identity-scoping` | `f543685a09e7bfc80128f32e403f915adec5de54` | `5654bc0b6f1e4abe4b547a125a5527e98b02e027` |
| TS-ISO-016 — Asset Metadata Visibility | `codex/ts-iso-016-asset-metadata-visibility` | `f5b245e8fc4dec7045b2a705be53803943de35af` | `c2701c6892d3fe5b2e8398ea20b70e61a97f3c1e` |

TS-ISO-012 and TS-ISO-013 branch from `UX-design-03` commit `1416dcf89cde8ff7219dc49c4f880d6f83be7de7`. TS-ISO-014 and TS-ISO-016 branch from `31df285cfe26dfa56fabb821c4d3b1cf5a09552a` (a later `UX-design-03` commit — the merge of the onboarding/email-verification work, itself an ancestor of `1416dcf8`'s successor history). All four merge-base cleanly onto the current `UX-design-03` tip; there is no expected conflict between them since each touches only its own new file.

---

## 1. What was validated, and how

Before writing this doc, every factual claim in each plan's "Current-state finding" table (the falsifiable, checkable part of each document — file names, function names, described behavior) was independently re-verified against the actual repository content on `origin/UX-design-03`, not summarized from the plan's own text. This was done with four parallel research passes (one per plan), each reading the real source files line-by-line and citing file:line evidence for every claim, followed by a manual second pass on this end to catch and correct one stale-branch-reference error the TS-ISO-016 pass made (see below).

**Result: all 10 + 9 + 9 + 10 = 38 current-state claims across the four plans were confirmed accurate.** Nothing in any plan was found to be fabricated or materially wrong. The validation surfaced:

- **4 additional unscoped call sites** for TS-ISO-012 (Google Sheets and SaaS-source Teiid registration have no tenant-scoping parameter at all — not even a fallback default; a cross-tenant reconciliation loop shares one global Teiid client across every tenant's active data sources in a single pass; `health.py`'s VDB health probe takes no tenant argument).
- **2 additional files** for TS-ISO-013 that touch first-party token handling and were missing from its file-change table (`web-ui/lib/api/voice.ts` bypasses the token-renewal path entirely; `app/main.py` wires the renewal header into CORS).
- **A corrected and strengthened dependency justification** for TS-ISO-014 on TS-ISO-004: an initial validation pass checked out a local `UX-design-03` branch ref that was 106 commits stale and wrongly concluded TS-ISO-004's RLS foundation doesn't exist on this branch. It does. More usefully, TS-ISO-004's own design doc (`docs/security/ts-iso-004-postgres-rls-design.md`) explicitly lists "replace service tenant `0` behavior with a concrete tenant claim or narrow control-plane role" as an intentional blocker it left open — which is exactly the gap TS-ISO-014 closes. This cross-reference is now recorded in TS-ISO-014's addendum.
- **Two protections credited as stronger than described** in TS-ISO-016 (vector grounding search already does a live cross-service permission check before querying Qdrant, not just a payload filter; the KG visibility filter already correctly mirrors the asset-level policy) alongside **one concrete named gap** (`document_families_reads.py` is a graph consumer that imports no visibility filter at all, unlike `project_graph.py`, the filter's only current caller).

Each finding above is now recorded as a "## Validation addendum" section (Section 13) appended to its respective plan file, with file:line citations, so an implementer starting from any of these four branches has both the original plan and an independently-verified correction/completeness layer to work from.

### A note on the stale-branch-reference risk

While validating TS-ISO-016, a bare `UX-design-03` local branch ref (not `origin/UX-design-03`) resolved to a checkout 106 commits behind the real branch tip, causing two claims to be provisionally (and wrongly) marked as contradicted. This was caught by cross-checking against `origin/UX-design-03` directly before being recorded anywhere. **Anyone continuing validation or implementation work on these plans should always verify against `origin/UX-design-03` (or `git fetch` first and diff against the fetched ref), never a local branch pointer that may be stale** — this repository has had a great deal of concurrent work land on `UX-design-03` recently (TS-ISO-004, TS-ISO-005, the KG-01 through KG-50 series, and the onboarding/email-verification work all merged in within the same broad timeframe as these four plans were authored), so a local checkout goes stale fast.

---

## 2. Merge

Each plan is an independent single-file addition with no cross-branch conflicts expected. Merge them in any order, or as four separate PRs — there is no reason to combine them into one PR since they touch four different files with no shared history to reconcile:

```bash
git fetch origin

git checkout -b merge-ts-iso-012 origin/UX-design-03
git merge origin/codex/ts-iso-012-data-plane-fallback-completion
# push / open PR

git checkout -b merge-ts-iso-013 origin/UX-design-03
git merge origin/codex/ts-iso-013-session-token-hardening
# push / open PR

git checkout -b merge-ts-iso-014 origin/UX-design-03
git merge origin/codex/ts-iso-014-service-identity-scoping
# push / open PR

git checkout -b merge-ts-iso-016 origin/UX-design-03
git merge origin/codex/ts-iso-016-asset-metadata-visibility
# push / open PR
```

Each merge adds exactly one new file under `docs/security/` (`ts-iso-012-data-plane-fallback-completion.md`, `ts-iso-013-session-token-hardening.md`, `ts-iso-014-service-identity-scoping.md`, `ts-iso-016-asset-metadata-visibility.md`). If merging all four into the same target branch sequentially, there is no conflict risk between them since none share a file.

**Merge rule:** do not edit the plan content while merging. If a reviewer disagrees with a specific claim or the Section 13 addendum, resolve it as a follow-up commit with its own file:line justification — don't silently rewrite the finding.

---

## 3. Verification

| Check | Result |
|---|---|
| Each branch contains exactly one plan file (plus its addendum commit) | Confirmed via `git diff --stat` against each branch's stated base commit — single-file diff in every case |
| Whitespace/trailing-space/EOF validation | `git diff --check` clean for all four branches against their correct base commits |
| Branch ancestry | `git merge-base <branch> <stated-base-commit>` returns the base commit itself for all four — each is a clean linear descendant |
| Commit SHA match against GitHub | All four original commit SHAs (`54ed09ae...`, `b68c50bc...`, `f543685a...`, `f5b245e8...`) match exactly what `git fetch origin` retrieved — no divergence |
| Factual claim validation | 38/38 current-state findings across all four plans confirmed accurate against `origin/UX-design-03`; see §1 |

No `pytest`/`vitest`/`ruff`/`mypy`/`tsc` run is applicable — these branches contain no application code.

---

## 4. Deploy

**There is nothing to deploy.** These four branches add planning documentation only. Merging them into `UX-design-03` and onward into the release branch has zero runtime effect.

What happens next is scheduling, not deployment:

1. Each plan's Section 6 ("Implementation work breakdown") and Section 10 ("Deployment sequence") describe multi-phase engineering efforts (weeks, not a single PR) that should be scheduled as their own tracked work, referencing the plan doc as the spec.
2. Recommended sequencing based on the dependency graph these four plans state on each other and on already-completed work:
   - **TS-ISO-014** (service identity scoping) has the clearest, most concrete unblock available right now — it closes a documented, named blocker in the already-merged TS-ISO-004 RLS foundation (see §1). It does not depend on TS-ISO-012 or TS-ISO-013 being done first.
   - **TS-ISO-012** (data-plane fallback) and **TS-ISO-013** (session tokens) are independent of each other and of TS-ISO-014; either can start in parallel.
   - **TS-ISO-016** (asset visibility) depends on the existing `ProjectAsset` visibility model and TS-ISO-005 (already merged and, per validation, more robust than the plan's own wording implies — see the TS-ISO-016 addendum) but not on the other three plans.
3. None of these four plans should be treated as "resolved" by merging the planning doc. Each plan's own closing line states its exit condition (e.g. "TS-ISO-012 must remain open until every isolated production mode... uses the fail-closed binding/gateway path...") — track the underlying finding as open in whatever issue tracker this repo uses until the actual implementation phases described in each plan are complete and tested.

---

## 5. Report back

Confirm all four PRs merge cleanly into `UX-design-03` with no conflicts. No further verification (test run, deploy, migration) applies to this merge.
