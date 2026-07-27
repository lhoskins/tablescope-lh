import { describe, expect, it } from "vitest";
import type { InsightDiagnostic } from "@/lib/api/home-intelligence";
import { buildDiagnosticChart } from "./diagnostic-chart";

/** 31 periods, ascending dates, descending revenue — the reported shape. */
function series(n = 31): Record<string, unknown>[] {
  return Array.from({ length: n }, (_, i) => ({
    month: `2024-${String((i % 12) + 1).padStart(2, "0")}-01`,
    RevenueUSD: 7_000_000 - i * 10_000,
  }));
}

function step(overrides: Partial<InsightDiagnostic> = {}): InsightDiagnostic {
  return {
    stage: "quantify",
    title: "Unusual RevenueUSD observations",
    question: "Which observations fall outside the expected range?",
    rationale: "Distinguishes a genuine outlier from ordinary variation.",
    finding: "1 observation outside the expected range.",
    intent: "detect_anomalies",
    presentation: { chart: "line", layers: ["confidence_band", "anomaly_marker"] },
    roles: { x: "month", y: "RevenueUSD" },
    result: { columns: ["month", "RevenueUSD"], rows: series() },
    ...overrides,
  };
}

describe("buildDiagnosticChart", () => {
  it("keeps every observation instead of capping at 25", () => {
    // The conversational builder slices to 25; evidence must stay complete.
    expect(buildDiagnosticChart(step())!.chart.data.series).toHaveLength(31);
  });

  it("preserves the projection's period order rather than ranking by value", () => {
    // The regression: a bar chart sorted by magnitude scrambled the date axis.
    const labels = buildDiagnosticChart(step())!.chart.data.series!.map((s) => s.label);
    expect(labels).toEqual(series().map((r) => r.month));
  });

  it("uses the chart family the intent asked for", () => {
    expect(buildDiagnosticChart(step())!.chart.type).toBe("line");
    const bar = buildDiagnosticChart(
      step({ presentation: { chart: "bar" }, intent: "contribution_to_change" }),
    );
    expect(bar!.chart.type).toBe("bar");
  });

  it("renders nothing for evidence the intent says is a table", () => {
    expect(buildDiagnosticChart(step({ presentation: { chart: "table" } }))).toBeNull();
    expect(buildDiagnosticChart(step({ presentation: undefined }))).toBeNull();
  });

  it("falls back to a line for a family the renderer does not draw", () => {
    const built = buildDiagnosticChart(step({ presentation: { chart: "wormhole" } }));
    expect(built!.chart.type).toBe("line");
  });

  it("marks the points the method flagged, not ones it re-derived", () => {
    const built = buildDiagnosticChart(
      step({ markers: { anomalyIndices: [17] } }),
    )!;
    expect(built.options.markedIndices).toEqual([17]);
    expect(built.anomalyRows).toEqual([17]);
    // The heuristic must stay off, or it would mark a different point.
    expect(built.options.showAnomalies).toBeUndefined();
  });

  it("drops flagged indices that fall outside the series", () => {
    const built = buildDiagnosticChart(
      step({ markers: { anomalyIndices: [-1, 5, 99] } }),
    )!;
    expect(built.anomalyRows).toEqual([5]);
  });

  it("translates the intent's analytical layers into renderer options", () => {
    const built = buildDiagnosticChart(step())!;
    expect(built.options.confidenceBand).toBe(true);
    const trend = buildDiagnosticChart(
      step({ presentation: { chart: "line", layers: ["regression_line"] } }),
    )!;
    expect(trend.options.showRegressionLine).toBe(true);
  });

  it("marks an explicit change point", () => {
    const built = buildDiagnosticChart(
      step({
        intent: "detect_change_point",
        presentation: { chart: "line", layers: ["change_point"] },
        markers: { changePointIndex: 8 },
      }),
    )!;
    expect(built.options.markedChangePointIndex).toBe(8);
  });

  it("plots the roles the projection declared, not column position", () => {
    const built = buildDiagnosticChart(
      step({
        roles: { x: "month", y: "RevenueUSD" },
        result: {
          // Measure first: positional guessing would plot dates as the value.
          columns: ["RevenueUSD", "month"],
          rows: [{ RevenueUSD: 5, month: "2024-01-01" }],
        },
      }),
    )!;
    expect(built.chart.data.series![0]).toEqual({ label: "2024-01-01", value: 5 });
  });

  it("carries a second measure when the projection has one", () => {
    const built = buildDiagnosticChart(
      step({
        presentation: { chart: "combo" },
        roles: { x: "month", y: "RevenueUSD", y2: "CostUSD" },
        result: {
          columns: ["month", "RevenueUSD", "CostUSD"],
          rows: [{ month: "2024-01-01", RevenueUSD: 10, CostUSD: 4 }],
        },
      }),
    )!;
    expect(built.chart.data.series![0].value2).toBe(4);
    expect(built.chart.roles?.y2).toBe("CostUSD");
  });

  it("coerces stringy numerics the query layer returns", () => {
    const built = buildDiagnosticChart(
      step({
        result: { columns: ["month", "RevenueUSD"], rows: [{ month: "2024-01-01", RevenueUSD: "1234.5" }] },
      }),
    )!;
    expect(built.chart.data.series![0].value).toBe(1234.5);
  });

  it("returns nothing when there is no evidence to draw", () => {
    expect(buildDiagnosticChart(step({ result: { columns: [], rows: [] } }))).toBeNull();
    expect(buildDiagnosticChart(step({ result: undefined }))).toBeNull();
  });

  it("charts a group comparison as ranked bars with the worst segment marked", () => {
    // The backend folds raw records into one entry per group before sending
    // these; charting the raw rows repeated one work centre down the axis.
    const built = buildDiagnosticChart(
      step({
        intent: "compare_multiple_groups",
        presentation: { chart: "bar" },
        roles: { x: "WorkCenterId", y: "UnitsScrapped" },
        markers: { anomalyIndices: [0] },
        result: {
          columns: ["WorkCenterId", "UnitsScrapped", "observations"],
          rows: [
            { WorkCenterId: "WC-007", UnitsScrapped: 42, observations: 60 },
            { WorkCenterId: "WC-001", UnitsScrapped: 10, observations: 55 },
            { WorkCenterId: "WC-002", UnitsScrapped: 9, observations: 51 },
          ],
        },
      }),
    )!;
    expect(built.chart.type).toBe("bar");
    expect(built.chart.data.series!.map((s) => s.label)).toEqual([
      "WC-007",
      "WC-001",
      "WC-002",
    ]);
    // Ranking must survive: the leading bar is the answer to "where".
    expect(built.chart.data.series![0].value).toBe(42);
    expect(built.options.markedIndices).toEqual([0]);
    expect(built.anomalyRows).toEqual([0]);
  });

  it("marks nothing when the backend found no clear leader", () => {
    const built = buildDiagnosticChart(
      step({
        intent: "compare_multiple_groups",
        presentation: { chart: "bar" },
        roles: { x: "WorkCenterId", y: "UnitsScrapped" },
        markers: {},
        result: {
          columns: ["WorkCenterId", "UnitsScrapped"],
          rows: [
            { WorkCenterId: "A", UnitsScrapped: 100 },
            { WorkCenterId: "B", UnitsScrapped: 99 },
          ],
        },
      }),
    )!;
    expect(built.options.markedIndices).toBeUndefined();
    expect(built.anomalyRows).toEqual([]);
  });

  it("charts a cross-reference as a scatter with its regression line", () => {
    const built = buildDiagnosticChart(
      step({
        intent: "relationship_numeric",
        presentation: { chart: "scatter", layers: ["regression_line"] },
        roles: { x: "UnitsScrapped", y: "OvertimeHours__ref" },
        crossReference: "mfg_labor_actuals_weekly_CSV",
        result: {
          columns: ["WeekStart", "UnitsScrapped", "OvertimeHours__ref"],
          rows: [
            { WeekStart: "2025-01-06", UnitsScrapped: 111, OvertimeHours__ref: 40 },
            { WeekStart: "2025-01-13", UnitsScrapped: 90, OvertimeHours__ref: 31 },
          ],
        },
      }),
    )!;
    expect(built.chart.type).toBe("scatter");
    expect(built.options.showRegressionLine).toBe(true);
    expect(built.chart.data.series![0]).toEqual({ label: "111", value: 40 });
  });
});

