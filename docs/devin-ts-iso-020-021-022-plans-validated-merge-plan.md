# Devin: merge + deploy — three standalone security implementation plans (TS-ISO-020, 021, 022)

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`

## Important: these branches were re-created here — the originally reported commits do not exist on GitHub

The three branches were reported as complete in a separate environment (`/workspace/scratch/7d2215b1bc67/tablescope-lh-iso-plans`, local commits `0dc77e01`/`4bddce4f`/`9bb9a75f`) that this session has no access to. When fetched here, all three remote branches pointed at the base commit `44322e06dcde507de053a5a529fc52acdcbce46c` — the plan content had not actually reached GitHub (the reporting session itself flagged this: "file-upload operations were interrupted by Auto-review").

Rather than validate content that didn't exist anywhere I could read, the full Markdown for all three plans was supplied directly in chat, verified, enhanced with a validation addendum, and pushed as new commits on top of the existing (base-pointing) branch refs. **The commit hashes below are the real, current state of these branches on GitHub — they do not match the originally reported local hashes, because those commits never left the other environment.** If that original local content differs from what's pasted/pushed here in some way this session couldn't see, reconcile before merging; otherwise treat the commits below as authoritative.

| Plan | Branch | Commit (pushed by this validation pass) |
|---|---|---|
| TS-ISO-020 — AI and Infrastructure Secrets Hardening | `codex/ts-iso-020-ai-infrastructure-secrets-hardening` | `a46dbcc56535eaf8c3624f454785301c58832a4e` |
| TS-ISO-021 — Security Audit and Alerting | `codex/ts-iso-021-security-audit-alerting` | `af183e811c07e5434345fd4d574330d65d8e7f8e` |
| TS-ISO-022 — Assurance and Release Gates | `codex/ts-iso-022-assurance-release-gates` | `156f675d7b5593175a70c72ffa6f8d11073f09da` |

All three branch from `UX-design-03` commit `44322e06dcde507de053a5a529fc52acdcbce46c` (confirmed to be the actual current tip of `origin/UX-design-03` at validation time) and add exactly one new Markdown file each under `docs/security/`. No conflict is expected merging any combination of these with each other or with the previously-merged TS-ISO-010/011/012/013/014/016 validation rounds.

## Why "no deploy" — same as every prior plan-validation round in this series

Each branch adds **one Markdown file and nothing else** — confirmed via `git diff --stat` on the commits this session created. No application code, no models, no migrations, no CI workflow changes, no Terraform changes. These are specifications for future hardening/process work, not the work itself. Merging them has zero runtime effect and needs no rebuild — but, as with the prior TS-ISO-010/011 doc, don't confuse "the plan merged" with "the finding is closed." TS-ISO-022 in particular is explicit about this exact distinction: it defines a release-gating *program*, and none of that program exists yet just because its planning doc is in the repo.

---

## 1. What was validated, and how

Every factual claim in each plan's "Current-state finding" table (Section 2) was independently re-verified against `origin/UX-design-03` — reading the real source files and CI workflow definitions line-by-line, not the plan's own prose. Three parallel research passes (one per plan) were run, each explicitly instructed to verify against `origin/UX-design-03` and never a bare local branch name.

**Result: 13 + 7 + 13 = 33 current-state claims across the three plans; 30 confirmed fully accurate, 3 needed a refinement (none were wrong in substance).** Each plan's own file now carries a "Validation addendum" section (Section 12) with the full findings; summary below.

### TS-ISO-020 (AI/infrastructure secrets)

- 12/13 claims fully accurate. The one refinement: the "static AWS keys remain supported" finding is true in effect, but the keys aren't read by `config.py` directly — they work through boto3's default credential chain picking them up from the container's environment. The fix target is the compose file and the boto3 client construction, not a `config.py` field.
- **New, high-value, isolated fix identified:** `TABLESCOPE_SECRET_KEY` has no fail-closed production startup check, even though `TABLESCOPE_AI_SIGNING_SECRET` already does. This is the same TS-ISO-007-style guard, just missing for the connector-encryption key. It can ship on its own, ahead of the full envelope-encryption redesign in Sections 5.4–5.5.
- Also found: the root/app-server instance's own `terraform/user-data.sh.tpl` secret-generation path is missing from the plan's file table (only `terraform/ai-server/*` is listed); neither cloud-init template `chmod`s the `.env` file it writes secrets into; and replay protection is asymmetric between the two AI HMAC directions (one has a fail-open Redis check, the other has no replay defense at all).

### TS-ISO-021 (security audit and alerting)

- 6/7 claims fully accurate. The refinement: `ON DELETE CASCADE` on tenant/project audit-event foreign keys applies to a subset of the six domain audit-event shapes found, not universally — two of them (`LLMAuditEvent`, `BillingEvent`) have no tenant_id/project_id column at all, so cascade doesn't apply to them at all.
- **Useful discovery:** `platform-api/app/services/billing_audit.py` already implements the exact canonical-event-name-constant + single-emit-function pattern Section 5.1's `SecurityEventV1` design describes. It's log-only (no persistence, no tenant binding, no alerting), but its emission-API shape should be the starting template for Phase A rather than a from-scratch design.

### TS-ISO-022 (assurance and release gates)

- 13/13 claims fully accurate, one confirmed *worse* than stated: there is no `dependabot.yml` anywhere in the repository — not even the passive, non-blocking dependency-update baseline the plan's wording leaves room for. The starting point for Section 6 Phase A's dependency-tracking work is zero, not "informal."
- Confirmed the plan's "Isolation tests" row with a full file listing (26 test files spanning tenant isolation, project access, seven Knowledge-Graph files, AI-proxy permissions, RLS context, datasource authorization, data planes, and SMB/network isolation) — the claim that useful component-level coverage exists is well-supported; the gap really is the missing cross-cutting matrix, exactly as stated.
- Noted one methodological limit: live GitHub branch-protection/ruleset state can't be verified by reading repository files — this validation pass could only confirm the *absence* of a `CODEOWNERS`/ruleset-as-code file in the repo, which is itself Section 5.8's whole point ("a repository file describing desired controls is not evidence that GitHub enforces them").

Full citations for every claim are in each plan's own Section 12 — read those before starting implementation.

---

## 2. Merge

```bash
git fetch origin

git checkout -b merge-ts-iso-020 origin/UX-design-03
git merge origin/codex/ts-iso-020-ai-infrastructure-secrets-hardening
# push / open PR

git checkout -b merge-ts-iso-021 origin/UX-design-03
git merge origin/codex/ts-iso-021-security-audit-alerting
# push / open PR

git checkout -b merge-ts-iso-022 origin/UX-design-03
git merge origin/codex/ts-iso-022-assurance-release-gates
# push / open PR
```

Each merge adds exactly one file. No conflicts expected in any combination.

**Merge rule:** do not edit plan content while merging. Disagreements with a specific claim or addendum become a follow-up commit with its own file:line justification.

---

## 3. Verification

| Check | Result |
|---|---|
| Base commit matches reported target | `44322e06dcde507de053a5a529fc52acdcbce46c` confirmed to be the actual `origin/UX-design-03` tip at validation time |
| Each branch contains exactly one plan file | Confirmed via `git diff --stat` on the commits pushed by this pass |
| Whitespace | `git diff --check` clean on all three new files |
| Factual claim validation | 33 current-state claims across three plans; 30 fully accurate, 3 refined (see §1) — no claim found materially wrong |

No `pytest`/`vitest`/`ruff`/`mypy`/`tsc` run is applicable — these branches contain no application code.

---

## 4. What happens next (scheduling, not deployment)

1. **TS-ISO-020's `TABLESCOPE_SECRET_KEY` startup guard (§1) is a small, isolated fix that can ship immediately**, independent of the plan's full envelope-encryption/KMS rollout — it's the same pattern already proven for the AI signing secret.
2. TS-ISO-021 depends on TS-ISO-014 (service identity), TS-ISO-017 (job reauthorization, not yet validated in this series), and TS-ISO-020 (this round) per its own header. TS-ISO-022 depends on evidence from *every* TS-ISO-004 through TS-ISO-021 plan. Sequence accordingly: TS-ISO-020's core work should land before TS-ISO-021's Phase B ("integrate TS-ISO-020 secret lifecycle"), and TS-ISO-022 is realistically the last of the three to actually enforce anything, since its whole design is to gate release on the *other* plans' evidence.
3. TS-ISO-022's Phase A (inventory and manifest schema) can and should start now in parallel with the others — it doesn't require any other plan's remediation to be complete, only for each plan's acceptance criteria to exist (which they now do, across this and the prior four validation rounds).
4. None of these three plans should be treated as closed by merging their planning docs. Track each as its own scheduled engineering effort against the plan doc as spec, the same way every prior TS-ISO validation round in this series has recommended.

---

## 5. Report back

Confirm all three PRs merge cleanly into `UX-design-03` with no conflicts. If the original `/workspace/scratch/7d2215b1bc67/tablescope-lh-iso-plans` environment's local commits (`0dc77e01`, `4bddce4f`, `9bb9a75f`) differ meaningfully from what's now on GitHub, flag that explicitly rather than silently overwriting — the content pushed here was taken verbatim from what was pasted into this session, which should match, but this session had no way to diff against the original local commits directly.
