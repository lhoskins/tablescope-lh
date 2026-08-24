# Home executive briefing and personas: Devin merge/deploy runbook

This change rebuilds Personal Home in the ITSM visual language as an executive
briefing. It replaces the inline My Focus editor with Home Settings, adds a
persona presentation lens, ranks authorized AI insights and indexed project
documents into Key Developments, and preserves the existing Pinned workspace.

Persona affects wording, ranking, and emphasis only. It does not expand tenant,
project, datasource, table, document, or row access.

## Branch and merge target

- Feature branch: `codex/home-itsm-executive-briefing`
- Merge target: `release/deploy-2026-08-07`

```bash
git fetch origin
git checkout release/deploy-2026-08-07
git pull --ff-only origin release/deploy-2026-08-07
git checkout codex/home-itsm-executive-briefing
git pull --ff-only origin codex/home-itsm-executive-briefing
git rebase origin/release/deploy-2026-08-07
```

If rebase changes the feature SHA, push the rebased feature branch and wait for
required checks before merging.

## Validation

Backend:

```bash
cd platform-api
python -m compileall -q app/routes/projects_aggregates.py app/routes/user_preferences.py tests/test_project_summaries.py
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
  components/tablescope/home/home-persona.test.ts \
  components/tablescope/home/personalized-home.test.tsx
npm run build
cd ..
```

## AI server lifecycle

The deterministic tests and build do not require the AI server because Home
composes previously authorized insight snapshots and document summaries. Devin
may start the AI server if a live end-to-end refresh is needed. Record its
initial state first. If this task starts it, stop it in cleanup after the checks,
including when a check fails. Do not stop an AI server that was already running.

## Merge and deploy

No database migration or new environment variable is required. The persona is
an additive key in the existing user preferences JSON.

```bash
git checkout release/deploy-2026-08-07
git merge --ff-only codex/home-itsm-executive-briefing
git push origin release/deploy-2026-08-07

docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui
docker compose ps platform-api platform-api-worker web-ui
docker compose logs --tail=150 platform-api platform-api-worker web-ui
```

## Required acceptance checks

1. Open Personal Home and confirm the AI Assistant is collapsed on the right by
   default. Expand it, resize its width, collapse it, and confirm the persisted
   behavior still works.
2. Confirm the page uses the ITSM visual language: grey Executive Brief, light
   blue metric cards with bold dark values, white Company Performance chart,
   grey supporting sections, and no colored side or bottom accents.
3. Confirm My Focus is absent from the page. Open **Home settings**, add/remove a
   focus topic, save, reload, and confirm it persists for the signed-in user.
4. Switch through CEO, CFO, CIO, CDO, Executive, IT Manager, IT Director,
   Manufacturing Director, Business Analyst, and Engineer. Confirm wording and
   ranked content change while the user's accessible project set does not.
5. Use a user with restricted project access and confirm Company Performance,
   metrics, Key Developments, and links contain no inaccessible insight or
   document.
6. Confirm Key Developments includes ranked AI insight cards and at least one
   AI-indexed document summary, such as a performance review or forecast.
7. Confirm Company Performance renders the highest-ranked chart-backed insight
   and links to its full analysis.
8. Confirm Material Risks, Opportunities, and Assigned Actions show current
   counts and valid links.
9. Confirm Pinned workspace remains below the briefing and existing Business
   Insight, Project Insight, dashboard-widget, and chart pins still render,
   refresh, move, and resize.
10. Confirm Home settings rejects an unsupported persona value through the API.

## Rollback

Redeploy the previous `platform-api` and `web-ui` SHA together. There is no
schema downgrade. Existing `home_persona` and `home_focus` preference values are
harmless additive JSON keys and can remain stored after rollback.
