import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WidgetRenderer } from "./WidgetRenderer";
import type { WidgetConfig } from "./types";

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

describe("WidgetRenderer routing", () => {
  it("shows an empty state when there is no data", () => {
    render(<WidgetRenderer widget={makeWidget({})} data={[]} />);
    expect(screen.getByText(/no data available/i)).toBeTruthy();
  });

  it("falls back to a table with a notice when the config is invalid", () => {
    const widget = makeWidget({ xColumn: "", xKey: undefined });
    render(<WidgetRenderer widget={widget} data={[{ Category: "A", Value: 5 }]} />);
    expect(screen.getByText(/showing table instead/i)).toBeTruthy();
  });

  it("renders a KPI value for kpi widgets", () => {
    const widget = makeWidget({ type: "kpi", aggregation: "count" });
    render(<WidgetRenderer widget={widget} data={[{ Value: 1234 }]} />);
    expect(screen.getByText("1,234")).toBeTruthy();
  });
});
