import { describe, expect, it } from "vitest";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";
import { buildChart } from "./ai-result-view";

const COLUMNS = ["category", "count"];
const ROWS = [
  { category: "Slips", count: 12 },
  { category: "Falls", count: 7 },
];

describe("buildChart", () => {
  it("emits the requested style as the chart subtype", () => {
    const viz: SuggestedVisualization = {
      type: "bar",
      xField: "category",
      yField: "count",
      style: "horizontal_bar",
    };
    const chart = buildChart(COLUMNS, ROWS, viz);
    expect(chart).not.toBeNull();
    expect(chart?.type).toBe("bar");
    expect(chart?.subtype).toBe("horizontal_bar");
  });

  it("leaves subtype undefined when no style is provided", () => {
    const viz: SuggestedVisualization = {
      type: "bar",
      xField: "category",
      yField: "count",
    };
    const chart = buildChart(COLUMNS, ROWS, viz);
    expect(chart?.subtype).toBeUndefined();
  });

  it("carries a pie donut style through", () => {
    const viz: SuggestedVisualization = {
      type: "pie",
      xField: "category",
      yField: "count",
      style: "donut",
    };
    const chart = buildChart(COLUMNS, ROWS, viz);
    expect(chart?.type).toBe("pie");
    expect(chart?.subtype).toBe("donut");
  });
});
