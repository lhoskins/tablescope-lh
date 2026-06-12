import { describe, expect, it } from "vitest";
import { validateChartConfig } from "./validateChartConfig";
import type { WidgetConfig } from "@/components/dashboard/types";

function makeWidget(overrides: Partial<WidgetConfig>): WidgetConfig {
  return {
    id: "w1",
    type: "bar",
    title: "Test",
    dataSource: { kind: "datasource", viewName: "v" },
    xColumn: "Category",
    yColumn: "Value",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    colSpan: 6,
    position: 0,
    ...overrides,
  };
}

describe("validateChartConfig", () => {
  it("passes for a well-formed bar chart", () => {
    const res = validateChartConfig(makeWidget({}), [{ Category: "A", Value: 5 }]);
    expect(res.ok).toBe(true);
    expect(res.errors).toHaveLength(0);
  });

  it("errors when a required X field is missing", () => {
    const res = validateChartConfig(makeWidget({ xColumn: "", xKey: undefined }));
    expect(res.ok).toBe(false);
    expect(res.errors[0]).toMatch(/category or X-axis/i);
  });

  it("errors when a required Y field is missing", () => {
    const res = validateChartConfig(makeWidget({ yColumn: "", yKey: undefined }));
    expect(res.ok).toBe(false);
    expect(res.errors.join(" ")).toMatch(/numeric value field/i);
  });

  it("errors and reports unknown chart types", () => {
    const res = validateChartConfig(makeWidget({ type: "sunburst" as WidgetConfig["type"] }));
    expect(res.ok).toBe(false);
    expect(res.errors[0]).toMatch(/unknown chart type/i);
  });

  it("warns about too many pie slices when grouping is off", () => {
    const widget = makeWidget({
      type: "pie",
      visualizationOptions: { groupSmallSlices: false, maxSlices: 3 },
    });
    const rows = [
      { Category: "A", Value: 1 },
      { Category: "B", Value: 2 },
      { Category: "C", Value: 3 },
      { Category: "D", Value: 4 },
    ];
    const res = validateChartConfig(widget, rows);
    expect(res.ok).toBe(true);
    expect(res.warnings.join(" ")).toMatch(/7 or fewer/i);
  });

  it("warns when dual axis has only one series", () => {
    const widget = makeWidget({ type: "line", visualizationOptions: { dualAxis: true } });
    const res = validateChartConfig(widget, [{ Category: "A", Value: 5 }]);
    expect(res.warnings.join(" ")).toMatch(/dual axis/i);
  });
});
