# R / ECharts Validation Procedure

This document records the repeatable validation package for the R-backed Analytical Method Engine and the Apache ECharts renderer feature gate.

## 1. Build-time configuration

`NEXT_PUBLIC_*` values are inlined at `web-ui` build time. The deployment defaults are now `default` for ECharts, `true` for R analytics, and `hybrid` for the analytical engine, so the values below are only needed to override or revert:

```bash
# On the app host
cd /home/ubuntu/tablescope
export NEXT_PUBLIC_ECHARTS_RENDERER_MODE=default   # off | shadow | new_widgets | default
export R_ANALYTICS_ENABLED=true
export ANALYTICAL_METHOD_ENGINE_MODE=hybrid          # off | readonly | hybrid

docker compose build web-ui platform-api platform-api-worker r-analytics
docker compose up -d web-ui platform-api platform-api-worker r-analytics nginx
docker compose restart nginx   # re-resolve upstreams after container recreation
```

Reverting to the Recharts-only, Python-only path:

```bash
export NEXT_PUBLIC_ECHARTS_RENDERER_MODE=off
export R_ANALYTICS_ENABLED=false
export ANALYTICAL_METHOD_ENGINE_MODE=off
docker compose build web-ui platform-api platform-api-worker
docker compose up -d web-ui platform-api platform-api-worker nginx
```

## 2. Service health

```bash
docker compose ps web-ui platform-api platform-api-worker r-analytics nginx
docker compose logs --tail 50 r-analytics platform-api web-ui
```

- `r-analytics` exposes only an internal `/health` endpoint on the default Docker network.
- `platform-api` `/health/live` should return 200.
- `nginx` should serve `https://app.tablescope.cloud/` without 502.

## 3. R canary

Run the non-destructive canary from inside the `platform-api` container:

```bash
docker compose exec platform-api python /app/scripts/validate_r_analytics.py
```

Expected output shape:

```json
{
  "status": "ok",
  "method": "r_descriptive_profile",
  "executionEngine": "r",
  "n": 5,
  "mean": 30,
  "median": 30,
  "min": 10,
  "max": 50,
  "parameterHash": "<16-char hex>",
  "inputDataHash": "<64-char hex>"
}
```

The script:

- calls the public `analytical_method_engine.analyze()` entry point,
- uses fixed test values `10, 20, 30, 40, 50`,
- passes `tenant_id=None` so tenant governance is not a dependency,
- exercises the active catalog, selection matrix, executor registry, R HTTP client, R handler, result envelope, and audit path,
- prints only metadata and hashes; raw rows and env vars are excluded.

## 4. ECharts dashboard smoke test

1. Build `web-ui` with `NEXT_PUBLIC_ECHARTS_RENDERER_MODE=default` and redeploy.
2. Log in as an admin/member of a tenant with at least one dashboard containing a supported widget type (`line`, `area`, `bar`, or `pie`).
3. Open a dashboard detail page, e.g. `https://app.tablescope.cloud/projects/{id}/dashboards/{dashboardId}`.
4. In the browser console, run:

```js
const markers = document.querySelectorAll('[data-testid="echarts-widget"]');
const canvases = document.querySelectorAll('canvas');
const recharts = document.querySelectorAll('.recharts-responsive-container');
console.log({ echartsMarkers: markers.length, canvases: canvases.length, recharts: recharts.length, attrs: Array.from(markers).map(m => m.getAttribute('data-chart-renderer')) });
```

Acceptance:

- `echartsMarkers` equals the number of supported (line/area/bar/pie) widgets on the dashboard.
- Every marker has `data-chart-renderer="echarts"`.
- At least one `<canvas>` is present inside an ECharts marker.
- Unsupported widgets (e.g. `combo`, `table`, `scatter`) still produce a `.recharts-responsive-container`.
- The dashboard refreshes without console errors and `echartsMarkers` / `canvases` are still present after clicking Refresh.

## 5. Automated component coverage

```bash
cd platform-api
pytest -q tests/test_executor_registry.py tests/test_result_envelope.py tests/test_intent_engine.py
cd ../web-ui
npm run typecheck
npm test -- --run
npm run build
```

## 6. Return to defaults

When validation is complete, rebuild with `NEXT_PUBLIC_ECHARTS_RENDERER_MODE=off` and `R_ANALYTICS_ENABLED=false` so the live environment returns to the proven Recharts/Python path unless ECharts is intentionally released.
