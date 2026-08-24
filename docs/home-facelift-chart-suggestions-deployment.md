# Personalized Home and Chart Suggestions: Devin merge/deploy runbook

This change rebuilds Home as a user-focused operational surface and upgrades
query suggestion preview into a chart-selection workflow.

## Branch and merge target

- Feature branch: `codex/home-facelift-chart-suggestions`
- Merge target: `release/deploy-2026-08-07`

```bash
git fetch origin
git checkout release/deploy-2026-08-07
git pull --ff-only origin release/deploy-2026-08-07
git checkout codex/home-facelift-chart-suggestions
git pull --ff-only origin codex/home-facelift-chart-suggestions
git rebase origin/release/deploy-2026-08-07
```

Run validation before merging. If the rebase changes the feature SHA, push the
rebased feature branch and let its required checks complete before merging.

## Validation

Backend:

```bash
cd platform-api
python -m compileall -q app/routes/projects_aggregates.py app/routes/user_preferences.py
python -m ruff check app/routes/projects_aggregates.py app/routes/user_preferences.py tests/test_project_summaries.py
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  python -m pytest tests/test_project_summaries.py -q
cd ..
```

Frontend:

```bash
cd web-ui
npm ci
npm run typecheck
npm test -- --run \
  components/tablescope/home/query-suggestion-preview-modal.test.tsx \
  components/tablescope/project/workspace/workspace-assistant-panel.test.tsx
npm run build
cd ..
```

## AI server lifecycle

The deterministic tests and application build do not require the AI server.
Devin has permission to start it only if the live Chart Suggestion acceptance
check needs an actual AI-generated query. Record whether the server was already
running. If this task starts it, stop it in a cleanup/finally step after the
acceptance checks, including when a check fails. Do not stop an AI server that
was already running before the task.

## Merge and deploy

Merge the reviewed feature branch into `release/deploy-2026-08-07`. This change
does not add an environment variable or database migration.

```bash
git checkout release/deploy-2026-08-07
git merge --ff-only codex/home-facelift-chart-suggestions
git push origin release/deploy-2026-08-07

docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui
docker compose ps platform-api platform-api-worker web-ui
docker compose logs --tail=150 platform-api platform-api-worker web-ui
```

## Required acceptance checks

1. Open Home and confirm the old New Query Suggestions, New Dashboard
   Suggestions, and suggestion-pill row are absent. Confirm their underlying
   project/AI workflows still work from their existing non-Home entry points.
2. Confirm Home shows My Focus, Action Highlights, Assigned to me, Updates for
   you, and Pinned workspace in that order.
3. Add and remove a My Focus item, reload, and confirm the choice persists for
   the signed-in user only.
4. Confirm action counts and assigned items include only visible projects and
   that another tenant cannot see them.
5. Expand the docked Home AI Assistant, ask a cross-project question, change its
   width, collapse it to the right, reload, and confirm width/collapse state and
   the Business Insights conversation are retained.
6. Open a New Query Suggestion preview. Confirm up to three compatible chart
   choices appear, selection updates the large preview, and data/SQL remain
   available on demand.
7. Select a widget size and choose **Add selected chart to Home**. Confirm the
   generated read-only query is saved once, a live widget is pinned, and the
   chart appears in Pinned workspace after Home reload.
8. Refresh live widgets and confirm the new chart reruns its saved query.
9. Confirm **Save Query** and **Add to Dashboard** still work from the preview.
10. Confirm existing Business Insight, Project Insight, dashboard widget, and
    insight-card pins continue to render and can be moved/resized.

## Rollback

Redeploy the previous `platform-api` and `web-ui` SHA together. There is no
schema downgrade. User focus values are stored as an additive key in the
existing preferences JSON, and queries/widgets created during acceptance remain
ordinary governed SavedQuery and HomePin records.
