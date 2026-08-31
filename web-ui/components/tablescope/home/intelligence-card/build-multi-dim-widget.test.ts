import { describe, expect, it } from "vitest";
import { buildMultiDimWidget } from "./build-multi-dim-widget";
import type { InsightChart } from "@/lib/api/home-intelligence";

function chart(overrides: Partial<InsightChart> = {}): InsightChart {
  return {
    type: "bar",
    subtype: "horizontal_bar",
    roles: { x: "customer", value: "revenue" },
    data: { rows: [] },
    ...overrides,
  } as InsightChart;
}

describe("buildMultiDimWidget auto value scale", () => {
  it("sets valueScale to millions when the chart's own values are in the millions", () => {
    const rows = [
      { customer: "Ironclad Industrial", revenue: 34_840_581.67 },
      { customer: "Atlas Rail", revenue: 6_662_211.37 },
    ];
    const widget = buildMultiDimWidget(chart({ data: { rows } }), rows);
    expect(widget.visualizationOptions?.valueScale).toBe("millions");
  });

  it("sets valueScale to thousands when the largest value is in the thousands", () => {
    const rows = [
      { customer: "A", revenue: 5_000 },
      { customer: "B", revenue: 800 },
    ];
    const widget = buildMultiDimWidget(chart({ data: { rows } }), rows);
    expect(widget.visualizationOptions?.valueScale).toBe("thousands");
  });

  it("leaves valueScale unset when every value is small", () => {
    const rows = [
      { customer: "A", revenue: 42 },
      { customer: "B", revenue: 7 },
    ];
    const widget = buildMultiDimWidget(chart({ data: { rows } }), rows);
    expect(widget.visualizationOptions?.valueScale).toBeUndefined();
  });

  it("preserves the type-specific visualizationOptions already set (e.g. radar legend)", () => {
    const rows = [{ subject: "Speed", value: 2_000_000, metric: "m1" }];
    const widget = buildMultiDimWidget(
      chart({ type: "radar", roles: { value: "value" }, data: { rows } }),
      rows,
    );
    expect(widget.visualizationOptions?.showLegend).toBe(true);
    expect(widget.visualizationOptions?.valueScale).toBe("millions");
  });
});
