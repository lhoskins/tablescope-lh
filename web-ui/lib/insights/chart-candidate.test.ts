import { describe, expect, it } from "vitest";
import type { InsightChart, VizCandidate } from "@/lib/api/home-intelligence";
import {
  applyCandidateToInsightChart,
  insightChartCandidateData,
} from "./chart-candidate";

const base: InsightChart = {
  type: "line",
  roles: { x: "month", y: "sales", value: "sales" },
  data: { rows: [{ month: "2026-01", sales: 10 }] },
};

function candidate(
  chartType: VizCandidate["decision"]["chartType"],
  chartStyle: string,
  fields: Partial<VizCandidate["decision"]>,
): VizCandidate {
  return {
    decision: {
      chartType,
      chartStyle,
      valueFormat: "number",
      reason: "test",
      confidence: 0.8,
      ...fields,
    },
    score: 0.8,
    supported: true,
  };
}

describe("applyCandidateToInsightChart", () => {
  it("uses candidate-specific axes instead of retaining stale base roles", () => {
    const chart = applyCandidateToInsightChart(
      base,
      candidate("heatmap", "", {
        xField: "site",
        yField: "incidents",
        y2Field: "priority",
      }),
    );
    expect(chart.roles).toMatchObject({
      x: "site",
      value: "incidents",
      y: "priority",
      group: "priority",
    });
  });

  it("maps a calendar heatmap to date and value without a group axis", () => {
    const chart = applyCandidateToInsightChart(
      { ...base, roles: { ...base.roles, group: "stale" } },
      candidate("heatmap", "calendar", {
        xField: "date",
        yField: "incidents",
      }),
    );
    expect(chart.subtype).toBe("calendar");
    expect(chart.roles).toMatchObject({ x: "date", value: "incidents" });
    expect(chart.roles?.group).toBeUndefined();
  });
});

describe("insightChartCandidateData", () => {
  it("reconstructs named columns from a compact two-value series", () => {
    const result = insightChartCandidateData({
      type: "combo",
      roles: { x: "month", y: "open", y2: "resolved" },
      seriesLabels: { value: "open", value2: "resolved" },
      data: {
        series: [
          { label: "2026-01", value: 8, value2: 9 },
          { label: "2026-02", value: 7, value2: 10 },
        ],
      },
    });
    expect(result.columns).toEqual(["month", "open", "resolved"]);
    expect(result.rows[0]).toEqual({ month: "2026-01", open: 8, resolved: 9 });
  });
});
