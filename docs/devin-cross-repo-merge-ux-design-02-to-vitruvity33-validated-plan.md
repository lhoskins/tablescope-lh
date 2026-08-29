# Devin: cross-repo merge — `UX-design-02` (lhoskins/tablescope-lh) → vitruvity33/tablescope

**Source repo:** `lhoskins/tablescope-lh`, branch `UX-design-02`, at `d1e274a3`
**Target repo:** `vitruvity33/tablescope`, branch **to be confirmed — see §0** (commonly `main` or `master`; do not assume)

This is a **different GitHub repository**, not a branch of the same repo — everything in the earlier `devin-*-validated-plan.md` docs in this repo (which all merge branches *within* `lhoskins/tablescope-lh`) does not directly apply here. Read §0 before running anything else in this doc; it decides which of the two procedures in §2 is safe to use.

---

## 0. Required first step: determine whether the two repos share history

`lhoskins/tablescope-lh` is a large monorepo — this branch's tree also carries `wildfly/`, `redash-8.0.0-7/`, `apache-maven-3.9.6/`, and Teiid vendor directories alongside the actual product code (`platform-api/`, `web-ui/`). Earlier work on this branch recorded that `UX-design-01` was originally **imported from a specific commit on `vitruvity33/tablescope`** (`4e8df9e32974e3011cdb39fa66b38aac723fd63e`), not created by forking it — that phrasing ("imported from") is a signal, not a confirmed fact about git ancestry, so verify directly:

```bash
git clone <vitruvity33/tablescope URL> vitruvity33-tablescope
cd vitruvity33-tablescope
git remote add lhoskins <lhoskins/tablescope-lh URL>
git fetch lhoskins UX-design-02

# Does a common ancestor exist between the two repos' histories?
git merge-base lhoskins/UX-design-02 origin/<target-branch> && echo "SHARED HISTORY" || echo "NO SHARED HISTORY"

# Sanity-check the actual size/shape of what fetching pulled in:
git log --oneline lhoskins/UX-design-02 -5
git diff --stat origin/<target-branch> lhoskins/UX-design-02 | tail -5
```

**If `git merge-base` finds nothing** (no shared history — the expected case if `vitruvity33/tablescope` is the original, smaller prototype repo and `lhoskins/tablescope-lh` diverged into an unrelated monorepo afterward): a normal `git merge` will refuse to run at all. Forcing it with `--allow-unrelated-histories` does **not** produce a clean feature merge — it unions the two trees, which for this pair of repos means every vendor directory (`wildfly/`, `redash-8.0.0-7/`, `apache-maven-3.9.6/`) lands in `vitruvity33/tablescope` alongside files it may not even use the same way. **Do not run that command without confirming with the repo owner first that this is actually intended** — the user has asked for the full branch merged as-is, but that instruction was given without seeing this diff-stat output, and this is the point where "as-is" and "acceptable" may diverge. Surface the diff-stat and file count from the check above before proceeding to §2B.

**If `git merge-base` finds a common ancestor** (the repos do share history — e.g. `vitruvity33/tablescope` is genuinely an upstream/fork relationship), use §2A instead: a normal merge is safe and will only bring in what's actually new relative to that shared point.

---

## 1. Merge rules — read first

1. **Do not modify, rewrite, refactor, rename, or reformat the delivered code.** Merge as-is. If conflicts arise, resolve them by preserving the delivered code from `UX-design-02` and adapting only the surrounding lines it touches — do not use conflict resolution as an opportunity to "clean up" anything.
2. Suspected bug in the delta → **report it in the PR description**, don't silently change it.
3. This is a push to an **external repository under a different account/org**. You almost certainly do not have direct push rights to `vitruvity33/tablescope`'s protected branches — plan on opening a pull request from a branch/fork you do control, not pushing directly to its default branch (see §3).

---

## 2A. Procedure — shared history confirmed

```bash
git fetch lhoskins UX-design-02
git checkout -b merge-ux-design-02 origin/<target-branch>
git merge lhoskins/UX-design-02
# resolve any conflicts per Rule 1, then:
git push <your-fork-or-branch> merge-ux-design-02
```
Open a PR from `merge-ux-design-02` against `vitruvity33/tablescope`'s `<target-branch>`.

## 2B. Procedure — no shared history (only after explicit confirmation per §0)

```bash
git fetch lhoskins UX-design-02
git checkout -b merge-ux-design-02 origin/<target-branch>
git merge --allow-unrelated-histories lhoskins/UX-design-02
# This will very likely need conflict resolution on files that exist in both
# trees with different content but no common ancestor -- resolve per Rule 1.
git push <your-fork-or-branch> merge-ux-design-02
```
Open a PR from `merge-ux-design-02` against `vitruvity33/tablescope`'s `<target-branch>`, and **call out in the PR description** that this merge brought in `lhoskins/tablescope-lh`'s full vendor/build trees (name them) so the reviewer isn't surprised by the file count.

---

## 3. What's in `UX-design-02`

Everything currently on `release/deploy-2026-08-07` (the full product monorepo — platform-api, web-ui, and the vendor/build trees noted in §0) **plus** this branch's own commits on top of it:
- `a163c7fb` / `39a051d1` — the Workspace feature (backend model + API, canvas UI, publish/unpublish/rename/delete, data-source Add-card fix)
- `e62d3c1e` — the nav-grid/sidebar-tree/project-Chats redesign (`docs/ux-workspace-redesign-gap-analysis.md`)
- Two `docs/devin-*.md` handoff docs

If `vitruvity33/tablescope` is meant to receive only the workspace/nav-redesign feature work — not the rest of this monorepo's history — §2B's unrelated-histories merge is the wrong tool regardless of what land here; that would instead be a manual patch/cherry-pick of just `platform-api/app/{models,routes}/workspace*.py`, `platform-api/alembic/versions/0086_workspaces.py`, and the `web-ui` files listed in the two Devin docs in this repo. Flagging this because it's the one thing that most changes what "correct" looks like here, and I can't confirm which is intended without checking the target repo.

---

## 4. Verify

Whichever procedure runs, before opening the PR: confirm the merged tree still builds/tests in `vitruvity33/tablescope`'s own CI or local equivalent of `npm run typecheck && npm test -- --run` (web-ui) — this repo's own test results (92 files / 552 tests passing) were verified against `lhoskins/tablescope-lh`'s tree and dependency versions, which may not be identical once merged into a different repo.
