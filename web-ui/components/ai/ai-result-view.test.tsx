import { describe, expect, it } from "vitest";
import { buildChart } from "@/components/ai/ai-result-view";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";

describe("buildChart high-cardinality handling", () => {
  const columns = ["AssignedTo", "AssetCount"];
  const rows = Array.from({ length: 30 }, (_, i) => ({
    AssignedTo: `EMP-1000${i}`,
    AssetCount: i + 1,
  }));

  it("ranks by the measure and caps to topN, keeping the leaders", () => {
    const viz: SuggestedVisualization = {
      type: "bar",
      xField: "AssignedTo",
      yField: "AssetCount",
      chartStyle: "horizontal_bar",
      topN: 12,
    };
    const chart = buildChart(columns, rows, viz);
    expect(chart).not.toBeNull();
    expect(chart?.type).toBe("bar");
    expect(chart?.subtype).toBe("horizontal_bar");
    const series = chart?.data.series ?? [];
    expect(series).toHaveLength(12);
    // Highest values first (EMP-100029 == 30 is the top).
    expect(series[0]?.value).toBe(30);
    expect(series[11]?.value).toBe(19);
  });

  it("leaves a small category set as a plain vertical bar in row order", () => {
    const smallRows = [
      { AssignedTo: "A", AssetCount: 1 },
      { AssignedTo: "B", AssetCount: 9 },
      { AssignedTo: "C", AssetCount: 4 },
    ];
    const chart = buildChart(columns, smallRows, { type: "bar" });
    expect(chart?.subtype).toBeUndefined();
    expect((chart?.data.series ?? []).map((s) => s.label)).toEqual([
      "A",
      "B",
      "C",
    ]);
  });
});
