/**
 * The conversational surfaces must not re-narrow the chart family.
 *
 * Two narrowings used to undo the shared ask pipeline's chart-fit ranking:
 * the backend `_ASK_AND_RUN_SURFACE` map (removed) and `buildChart`'s
 * `pie/line/bar` collapse here. Everything renders through EChartsWidget via
 * WidgetRenderer, so a scatter or heatmap answer must survive to the renderer.
 */
import { describe, expect, it } from "vitest";
import { buildChart } from "./ai-result-view";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";

const columns = ["region", "revenue"];
const rows = [
  { region: "North", revenue: 10 },
  { region: "South", revenue: 20 },
  { region: "East", revenue: 30 },
];

function build(type: SuggestedVisualization["type"], extra: Partial<SuggestedVisualization> = {}) {
  return buildChart(columns, rows, {
    type,
    xField: "region",
    yField: "revenue",
    ...extra,
  } as SuggestedVisualization);
}

describe("buildChart preserves the engine's chart family", () => {
  it("keeps the classic families", () => {
    expect(build("bar")?.type).toBe("bar");
    expect(build("line")?.type).toBe("line");
    expect(build("pie")?.type).toBe("pie");
  });

  it("no longer collapses richer families to bar", () => {
    for (const family of ["scatter", "heatmap", "boxplot", "treemap", "funnel", "sankey", "radar"] as const) {
      expect(build(family)?.type, `${family} was collapsed`).toBe(family);
    }
  });

  it("still returns null for table and empty results", () => {
    expect(build("table")).toBeNull();
    expect(buildChart([], [], { type: "bar" } as SuggestedVisualization)).toBeNull();
  });

  it("keeps the engine's subtype and top-N ranking for bars", () => {
    const chart = build("bar", { chartStyle: "horizontal_bar", topN: 2 });
    expect(chart?.subtype).toBe("horizontal_bar");
    const series = chart?.data.series ?? [];
    expect(series).toHaveLength(2);
    // Ranked by measure, so the leaders survive the cap.
    expect(series[0].value).toBe(30);
  });
});
