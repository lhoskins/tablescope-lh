import { describe, expect, it } from "vitest";
import { toOperationalChartData } from "./OperationalInsightGrid";
import type { WidgetConfig } from "./types";

function baseWidget(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
  return {
    id: "w1",
    type: "line",
    title: "Revenue Actual vs Forecast",
    dataSource: { kind: "query", queryId: 1 },
    xColumn: "month",
    yColumn: "actual_revenue",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    colSpan: 8,
    position: 0,
    ...overrides,
  };
}

describe("toOperationalChartData", () => {
  it("builds two named series from yColumn and y2Column for a combo widget", () => {
    const widget = baseWidget({ type: "combo", y2Column: "forecast_revenue" });
    const rows = [
      { month: "2026-01", actual_revenue: 100000, forecast_revenue: 98000 },
      { month: "2026-02", actual_revenue: 110000, forecast_revenue: 105000 },
    ];

    const chart = toOperationalChartData(widget, rows);

    expect(chart.series).toHaveLength(2);
    expect(chart.series[0]).toEqual({ name: "Actual Revenue", x: ["2026-01", "2026-02"], y: [100000, 110000] });
    expect(chart.series[1]).toEqual({ name: "Forecast Revenue", x: ["2026-01", "2026-02"], y: [98000, 105000] });
    expect(chart.categories).toEqual(["2026-01", "2026-02"]);
    // A combo widget must keep its "combo" chartType through to ItsmChart --
    // falling through to the default "line" mapping renders BOTH series as
    // lines (losing the bar/line distinction the preview step already
    // grounded) even though the series data itself is built correctly.
    expect(chart.chartType).toBe("combo");
  });

  it("falls back to a single series when a combo widget has no y2Column", () => {
    const widget = baseWidget({ type: "combo" });
    const rows = [{ month: "2026-01", actual_revenue: 100000 }];

    const chart = toOperationalChartData(widget, rows);

    expect(chart.series).toHaveLength(1);
    expect(chart.series[0].name).toBe("Revenue Actual vs Forecast");
  });

  it("pivots into one series per group when the widget has a groupByColumn", () => {
    const widget = baseWidget({ groupByColumn: "region", yColumn: "count" });
    const rows = [
      { month: "2026-01", region: "East", count: 10 },
      { month: "2026-01", region: "West", count: 5 },
      { month: "2026-02", region: "East", count: 12 },
    ];

    const chart = toOperationalChartData(widget, rows);

    expect(chart.series.map((s) => s.name).sort()).toEqual(["East", "West"]);
    expect(chart.categories).toEqual(["2026-01", "2026-02"]);
  });

  it("builds a single named series for a plain widget", () => {
    const widget = baseWidget({ yColumn: "count" });
    const rows = [{ month: "2026-01", count: 7 }];

    const chart = toOperationalChartData(widget, rows);

    expect(chart.series).toEqual([{ name: "Revenue Actual vs Forecast", x: ["2026-01"], y: [7] }]);
  });

  it("carries the widget's visualizationOptions through so ItsmChart can scale/format its axis", () => {
    const widget = baseWidget({
      yColumn: "count",
      visualizationOptions: { valueScale: "millions", currencySymbol: "€" },
    });

    const chart = toOperationalChartData(widget, [{ month: "2026-01", count: 7 }]);

    expect(chart.visualizationOptions).toEqual({ valueScale: "millions", currencySymbol: "€" });
  });

  it("leaves visualizationOptions undefined when the widget has none", () => {
    const widget = baseWidget({ yColumn: "count" });

    const chart = toOperationalChartData(widget, [{ month: "2026-01", count: 7 }]);

    expect(chart.visualizationOptions).toBeUndefined();
  });
});
