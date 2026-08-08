import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { WidgetRenderer } from "./WidgetRenderer";
import type { WidgetConfig } from "./types";

const { chartMock, initMock, useMock } = vi.hoisted(() => {
  const chartMock = {
    setOption: vi.fn(),
    on: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  };
  const initMock = vi.fn(() => chartMock);
  const useMock = vi.fn();
  return { chartMock, initMock, useMock };
});

vi.mock("echarts/core", () => ({
  use: useMock,
  init: initMock,
}));

function makeWidget(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
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

const data = [
  { Category: "A", Value: 5 },
  { Category: "B", Value: 10 },
];

describe("WidgetRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows an empty state when there is no data", () => {
    render(<WidgetRenderer widget={makeWidget()} data={[]} />);
    expect(screen.getByText(/no data available/i)).toBeTruthy();
  });

  it("still renders the chart when a column is unset", () => {
    const widget = makeWidget({ xColumn: "", xKey: undefined });
    const { container } = render(<WidgetRenderer widget={widget} data={[{ Category: "A", Value: 5 }]} />);
    expect(screen.queryByText(/showing table instead/i)).toBeNull();
    expect(screen.queryByText(/no data available/i)).toBeNull();
    expect(container.querySelector("[data-testid='echarts-widget']")).toBeTruthy();
  });

  it("renders a KPI value for kpi widgets", () => {
    const widget = makeWidget({ type: "kpi", aggregation: "count" });
    render(<WidgetRenderer widget={widget} data={[{ Value: 1234 }]} />);
    expect(screen.getByText("1,234")).toBeTruthy();
  });

  it("renders every chart type through ECharts", async () => {
    const types: Array<WidgetConfig["type"]> = ["line", "bar", "area", "pie", "combo", "scatter", "radar", "radial_bar", "treemap", "funnel", "sankey"];
    for (const type of types) {
      vi.clearAllMocks();
      const { unmount } = render(<WidgetRenderer widget={makeWidget({ type })} data={data} />);
      await new Promise((r) => setTimeout(r, 0));
      expect(screen.getByTestId("echarts-widget")).toBeTruthy();
      expect(screen.getByTestId("echarts-widget").getAttribute("data-chart-renderer")).toBe("echarts");
      expect(initMock).toHaveBeenCalledTimes(1);
      unmount();
    }
  });

  it("has no legacy chart markup anywhere", () => {
    const { container } = render(<WidgetRenderer widget={makeWidget({ type: "bar" })} data={data} />);
    expect(container.querySelectorAll("[data-chart-renderer]").length).toBe(1);
    expect(screen.getByTestId("echarts-widget").getAttribute("data-chart-renderer")).toBe("echarts");
  });
});
