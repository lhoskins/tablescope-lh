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

  it("renders the calendar heatmap subtype with a calendar coordinate system", async () => {
    const data = Array.from({ length: 28 }, (_, index) => ({
      Date: `2026-08-${String(index + 1).padStart(2, "0")}`,
      Value: index % 8,
    }));
    render(
      <EChartsWidget
        widget={makeWidget({
          type: "heatmap",
          chartSubtype: "calendar",
          xColumn: "Date",
          yColumn: "Value",
        })}
        {...defaultProps}
        data={data}
        xKey="Date"
        yKey="Value"
        chartData={data}
      />,
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    const option = chartMock.setOption.mock.calls.at(-1)?.[0];
    expect(option.calendar.range).toEqual(["2026-08-01", "2026-08-28"]);
    expect(option.series[0].coordinateSystem).toBe("calendar");
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

// ── Explicit annotations from an analysis ───────────────────────────────────
//
// A method that fits a model (R's ETS-based detect_anomalies) can flag a point
// that sits inside 2 sigma of the mean. The widget's own heuristic would then
// mark a *different* point than the finding names, so supplied indices win.

describe("EChartsWidget explicit markers", () => {
  // A flat baseline with one clear outlier at index 9, so the widget's own
  // 2-sigma rule demonstrably fires there — that makes the override tests a
  // genuine conflict rather than a vacuous one. (A single extreme spike in a
  // tiny series inflates sigma enough to mask itself.)
  const SPIKY = [
    { Category: "A", Value: 10 },
    { Category: "B", Value: 11 },
    { Category: "C", Value: 12 },
    { Category: "D", Value: 10 },
    { Category: "E", Value: 11 },
    { Category: "F", Value: 12 },
    { Category: "G", Value: 10 },
    { Category: "H", Value: 11 },
    { Category: "I", Value: 12 },
    { Category: "J", Value: 60 },
  ];
  const spikyProps = { ...defaultProps, data: SPIKY, chartData: SPIKY };

  beforeEach(() => vi.clearAllMocks());
  afterEach(() => cleanup());

  function markPoints() {
    const option = chartMock.setOption.mock.calls.at(-1)?.[0];
    return option?.series?.[0]?.markPoint?.data ?? [];
  }

  it("marks the supplied point even when the 2-sigma rule would not", async () => {
    render(
      <EChartsWidget
        widget={makeWidget({
          type: "line",
          visualizationOptions: { markedIndices: [1] },
        })}
        {...spikyProps}
      />,
    );
    await new Promise((r) => setTimeout(r, 0));
    const coords = markPoints().map((p: { coord: number[] }) => p.coord[0]);
    expect(coords).toEqual([1]);
  });

  it("supplied indices override the re-derived anomalies", async () => {
    render(
      <EChartsWidget
        widget={makeWidget({
          type: "line",
          // The heuristic would pick index 9 (the spike); the method said 0.
          visualizationOptions: { showAnomalies: true, markedIndices: [0] },
        })}
        {...spikyProps}
      />,
    );
    await new Promise((r) => setTimeout(r, 0));
    const coords = markPoints().map((p: { coord: number[] }) => p.coord[0]);
    expect(coords).toEqual([0]);
    expect(coords).not.toContain(9);
  });

  it("still re-derives anomalies when nothing was supplied", async () => {
    render(
      <EChartsWidget
        widget={makeWidget({ type: "line", visualizationOptions: { showAnomalies: true } })}
        {...spikyProps}
      />,
    );
    await new Promise((r) => setTimeout(r, 0));
    const coords = markPoints().map((p: { coord: number[] }) => p.coord[0]);
    expect(coords).toEqual([9]);
  });

  it("ignores out-of-range indices rather than plotting a phantom point", async () => {
    render(
      <EChartsWidget
        widget={makeWidget({ type: "line", visualizationOptions: { markedIndices: [99] } })}
        {...spikyProps}
      />,
    );
    await new Promise((r) => setTimeout(r, 0));
    expect(markPoints()).toHaveLength(0);
  });

  it("marks an explicit change point over the largest-jump guess", async () => {
    render(
      <EChartsWidget
        widget={makeWidget({
          type: "line",
          visualizationOptions: { showChangePoint: true, markedChangePointIndex: 1 },
        })}
        {...spikyProps}
      />,
    );
    await new Promise((r) => setTimeout(r, 0));
    const coords = markPoints().map((p: { coord: number[] }) => p.coord[0]);
    expect(coords).toEqual([1]);
  });
});
