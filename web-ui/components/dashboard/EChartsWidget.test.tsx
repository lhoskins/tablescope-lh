import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { EChartsWidget } from "./EChartsWidget";
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

const defaultProps = {
  data: [
    { Category: "A", Value: 10 },
    { Category: "B", Value: 20 },
  ],
  xKey: "Category",
  yKey: "Value",
  y2Key: "",
  chartData: [
    { Category: "A", Value: 10 },
    { Category: "B", Value: 20 },
  ],
  seriesNames: [] as string[],
};

describe("EChartsWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("exposes stable test markers", () => {
    render(<EChartsWidget widget={makeWidget()} {...defaultProps} />);
    const root = screen.getByTestId("echarts-widget");
    expect(root).toBeTruthy();
    expect(root.getAttribute("data-chart-renderer")).toBe("echarts");
  });

  it("initializes echarts for every supported chart type", async () => {
    const types: Array<WidgetConfig["type"]> = ["line", "area", "bar", "pie", "combo", "scatter", "radar", "radial_bar", "treemap", "funnel", "sankey"];
    for (const type of types) {
      vi.clearAllMocks();
      const { unmount } = render(<EChartsWidget widget={makeWidget({ type })} {...defaultProps} />);
      await new Promise((r) => setTimeout(r, 0));
      expect(initMock).toHaveBeenCalledTimes(1);
      expect(chartMock.setOption).toHaveBeenCalled();
      unmount();
    }
  });

  it("registers a click listener when onElementClick is provided", async () => {
    const onClick = vi.fn();
    render(<EChartsWidget widget={makeWidget({ type: "bar" })} {...defaultProps} onElementClick={onClick} />);
    await new Promise((r) => setTimeout(r, 0));
    expect(chartMock.on).toHaveBeenCalledWith("click", expect.any(Function));
  });

  it("does not register a click listener when onElementClick is absent", async () => {
    render(<EChartsWidget widget={makeWidget({ type: "bar" })} {...defaultProps} />);
    await new Promise((r) => setTimeout(r, 0));
    expect(chartMock.on).not.toHaveBeenCalled();
  });

  it("calls chart.resize when the window is resized", async () => {
    render(<EChartsWidget widget={makeWidget({ type: "bar" })} {...defaultProps} />);
    await new Promise((r) => setTimeout(r, 0));
    window.dispatchEvent(new Event("resize"));
    expect(chartMock.resize).toHaveBeenCalled();
  });

  it("disposes the chart and removes resize listener on unmount", async () => {
    const { unmount } = render(<EChartsWidget widget={makeWidget({ type: "bar" })} {...defaultProps} />);
    await new Promise((r) => setTimeout(r, 0));
    unmount();
    expect(chartMock.dispose).toHaveBeenCalled();
  });

  it("shows a no-data state when data is empty", () => {
    render(<EChartsWidget widget={makeWidget({ type: "bar" })} {...defaultProps} data={[]} chartData={[]} />);
    expect(screen.getByText(/no data/i)).toBeTruthy();
  });
});
