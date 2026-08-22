import { describe, expect, it } from "vitest";
import { operationalLayout, OPERATIONAL_IMPROVEMENTS_LAYOUT_ID } from "./operationalLayout";
import type { WidgetConfig } from "@/components/dashboard/types";

function widget(id: string, type: WidgetConfig["type"], chartSubtype?: string): WidgetConfig {
  return {
    id,
    type,
    chartSubtype,
    title: id,
    dataSource: { kind: "query", queryId: 1 },
    position: 0,
    visualizationOptions: chartSubtype === "horizontal_bar" ? { barLayout: "horizontal" } : {},
  } as WidgetConfig;
}

describe("operationalLayout", () => {
  it("places KPIs first and reserves the bottom-right slot for opportunities", () => {
    const layout = operationalLayout([
      widget("trend", "line"),
      widget("revenue", "kpi"),
      widget("backlog", "kpi"),
      widget("ranking", "bar", "horizontal_bar"),
    ]);
    expect(layout.find((item) => item.i === "revenue")).toMatchObject({ y: 0, w: 6, h: 2 });
    expect(layout.find((item) => item.i === "backlog")).toMatchObject({ y: 0, w: 6, h: 2 });
    expect(layout.find((item) => item.i === OPERATIONAL_IMPROVEMENTS_LAYOUT_ID)).toMatchObject({ x: 9, w: 3 });
  });

  it("never permits a horizontal ranking to become full width", () => {
    const ranking = widget("ranking", "bar", "horizontal_bar");
    ranking.gridW = 12;
    expect(operationalLayout([ranking])[0]).toMatchObject({ w: 6, maxW: 6 });
  });
});
