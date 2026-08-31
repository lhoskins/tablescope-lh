# Devin: merge + deploy — insight-card number formatting

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-insight-card-number-formatting`
**Base:** `release/deploy-2026-08-07`

**1 commit · 19 files · frontend only (`web-ui/`) · no migration · no backend/WAR changes · all tests green (§3)**

---

## 1. What this fixes

Two things, from a screenshot of the Business Insight page and the Home "Company performance" card:

1. **Chart axes/bar-end labels showed raw, unscaled numbers.** The Business Insight page's cards showed `5,000,000` (commas, no scale) on the Y axis instead of `5M`; Home's "Company performance" card was worse — `34840581.67` with **no commas at all** — because that specific chart's widget never set `visualizationOptions` in the first place, and `ItsmChart.tsx` deliberately skips every formatter when that's absent (its own comment explains this is meant to leave real ITSM ticket-count presets unformatted; this AI-ranked chart was getting caught by that same guard by accident, not by design).
2. **Percent values had inconsistent precision** — most of the app rounded to 1 decimal (`25.0%`), some to 0. Every percent display in `web-ui` now renders to exactly 2 decimals (`25.02%`, `110.30%`), per explicit request.

Also implemented, stated directly in the request: hovering a chart value now always shows the full, exact number with thousand separators and two decimals (`34,840,581.67`), regardless of what K/M scale its axis tick or bar label is showing.

---

## 2. What changed and why

**`components/dashboard/EChartsWidget/format-number.tsx`** — two new exports, `formatNumber`'s own behavior otherwise untouched except the percent branch:
- `autoValueScale(values)`: given a chart's own numeric values, picks one shared display unit — `"millions"` if the largest magnitude is ≥1,000,000, `"thousands"` if ≥1,000, otherwise none. **Deliberately not the same as the existing `"auto"` `ValueScale` enum member** — that value is documented and tested (`format-number.test.ts`) to mean "no forced scale, identical to omitting it" for a user's own designer-configured dashboard charts, and changing that meaning would have silently altered how every existing saved dashboard scale picker behaves. `autoValueScale`'s result is instead resolved to a concrete `"millions"`/`"thousands"`/`undefined` value *before* it's ever assigned to `visualizationOptions.valueScale`, so `formatNumber`, `formatAxisNumber`, and every chart builder that already correctly consumes `valueScale` pick it up with no changes needed there at all.
- `formatFullPrecision(v, format, currencySymbol)`: the tooltip-only full-precision renderer described above.
- `formatNumber`'s `percent` branch: `.toFixed(1)` → `.toFixed(2)`.

**`components/dashboard/EChartsWidget/tooltip-formatter.tsx`**: now calls `formatFullPrecision` instead of `formatNumber` with the axis scale — this is a global change to every chart's hover tooltip (bar/line/combo, anywhere `tooltipFormatter` is used, including `ItsmChart.tsx`), not scoped to insight cards, since exact-value-on-hover is a reasonable improvement everywhere.

**Where `autoValueScale` is wired in** — every insight-card chart-widget builder, since these are the two surfaces in the screenshots:
- `components/tablescope/home/intelligence-card/build-multi-dim-widget.tsx` — the shared builder used by both the Business Insight page and Home's primary chart path. Computes the scale from `dataRows` using the widget's resolved `yColumn`/`y2Column` and merges it into the `visualizationOptions` it already returns.
- `components/tablescope/home/intelligence-card/insight-chart-view.tsx` — its two `chart.data.series`-based fallback branches (used when the insight has no `data.rows`) now compute and set `valueScale` the same way.
- `components/tablescope/home/personalized-home.tsx` — `toItsmPerformanceChart`'s `series`-based fallback branch previously built a `WidgetConfig` with **no `visualizationOptions` at all**, which is the direct cause of the completely-unformatted Home chart in the screenshot. It now sets one (even if `autoValueScale` finds no scale to apply, the object itself being present is what turns `ItsmChart.tsx`'s formatters back on for this chart).

**Percent-decimal fix, applied everywhere a hardcoded 1-decimal percent format was found** (`grep`-verified, not a guess): `signed-percent.tsx`, `WidgetRenderer.tsx` (KPI delta indicator), `lib/insights/time-series.ts::formatPercentChange` (feeds `percent-change-summary-table`'s cells/aria-labels), `components/ai/DashboardWidgetCard.tsx`, `business-context-screen/fmt-number.tsx`, `metadata-catalog-screen.tsx`, and both `ItsmDashboardContent.tsx`/`ItsmInsightsDashboardContent.tsx` (2 call sites each). **Deliberately left alone:** three confidence-badge percentages in `upload/AIFileUploadWizard/file-review-card.tsx` that already round to 0 decimals (`85%`) — already compliant with "no more than 2 decimals," and adding `.00` to a rough AI-confidence badge would add visual noise without benefit; not part of what was shown/asked about. Flag if you want those changed too.

---

## 3. Verification

| Suite | Result |
|---|---|
| `web-ui` `tsc --noEmit` | clean |
| `web-ui` `vitest run` | **568 / 568 passed** (94 files) |
| `web-ui` `next lint` | clean (only pre-existing `max-lines`/`exhaustive-deps` warnings in unrelated files) |

Three pre-existing test files asserted the old 1-decimal percent strings verbatim (`"+5.0%"`, `"4.2%"`, `"↓ 6.8%"`, etc.) and needed their expected strings updated to match the new 2-decimal format — not because they were testing something wrong, just because the string literals baked in the old precision:
- `percent-change-summary-table.test.tsx`
- `generate-dashboard-modal.test.tsx`
- `WidgetRenderer.test.tsx`

New/extended test coverage: `format-number.test.ts` (percent precision, `autoValueScale`, `formatFullPrecision`), `signed-percent.test.ts` (new file), `build-multi-dim-widget.test.ts` (new file — locks in the millions/thousands/none scale selection and confirms other `visualizationOptions` like the radar legend flag survive the merge).

```bash
cd web-ui && npx tsc --noEmit && npx vitest run && npx next lint
```

---

## 4. Deploy

Frontend-only, no migration, no WAR/backend change.

```bash
docker compose build web-ui
docker compose up -d web-ui
```

No cache to clear — this only changes how already-fetched numbers are rendered client-side, not what data is fetched or stored.

---

## 5. Verify live

- **Business Insight page**: open a card with a bar/line/combo chart whose values are in the millions (e.g. a revenue chart) — axis and bar-end labels should read `5M`/`34.8M` style, not `5,000,000`.
- **Home page, "Company performance" card**: same check — this was the specifically broken (unformatted, no commas) case in the report. Confirm it now matches the Business Insight styling.
- **Hover any bar/point** on either surface — the tooltip should show the exact value with commas and two decimals (`34,840,581.67`), even though the axis/label shows the abbreviated `34.8M`.
- **A chart whose values are all small** (under 1,000) should render unchanged — no scale suffix, plain numbers. `autoValueScale` returning "no scale" for small charts is correct, not a regression.
- **Any percent display** across the app (dashboards, ITSM cards, business-context screen, metadata catalog) should show exactly two decimals — spot-check a couple of surfaces outside the two in the screenshots to confirm the global fix landed.
- **A saved dashboard with an explicit `valueScale`/`yAxisScale` chosen by a user in the chart designer** should render exactly as before — this branch does not touch how those designer-set options behave, only the two insight-card surfaces that had no scale set at all.

---

## 6. Report back

`vitest`/`tsc`/lint totals in your own environment; screenshots of the Business Insight and Home charts now showing scaled axis labels; a screenshot of a tooltip showing the full-precision hover value; and confirmation that an existing user-configured dashboard's chart scale setting is unaffected.
