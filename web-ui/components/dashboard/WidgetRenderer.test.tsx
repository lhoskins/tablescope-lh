import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { WidgetRenderer } from "./WidgetRenderer";
import type { WidgetConfig } from "./types";

const chartMock = {
  setOption: vi.fn(),
  on: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
};

const initMock = vi.fn(() => chartMock);

vi.mock("echarts", () => ({
  default: { init: initMock },
  init: initMock,
}));

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

const data = [
  { Category: "A", Value: 5 },
  { Category: "B", Value: 10 },
];

describe("WidgetRenderer routing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "off");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it("shows an empty state when there is no data", () => {
    render(<WidgetRenderer widget={makeWidget({})} data={[]} />);
    expect(screen.getByText(/no data available/i)).toBeTruthy();
  });

  it("still renders the chart (no table fallback) when a column is unset", () => {
    const widget = makeWidget({ xColumn: "", xKey: undefined });
    const { container } = render(
      <WidgetRenderer widget={widget} data={[{ Category: "A", Value: 5 }]} />
    );
    expect(screen.queryByText(/showing table instead/i)).toBeNull();
    expect(screen.queryByText(/no data available/i)).toBeNull();
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("renders a KPI value for kpi widgets", () => {
    const widget = makeWidget({ type: "kpi", aggregation: "count" });
    render(<WidgetRenderer widget={widget} data={[{ Value: 1234 }]} />);
    expect(screen.getByText("1,234")).toBeTruthy();
  });

  it("renders ECharts for supported widgets in default mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "default");
    render(<WidgetRenderer widget={makeWidget({ type: "line" })} data={data} />);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByTestId("echarts-widget")).toBeTruthy();
    expect(screen.getByTestId("echarts-widget").getAttribute("data-chart-renderer")).toBe("echarts");
    expect(initMock).toHaveBeenCalled();
  });

  it("preserves the Recharts path in off mode", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "off");
    const { container } = render(<WidgetRenderer widget={makeWidget({ type: "bar" })} data={data} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("renders ECharts in new_widgets mode only when renderer is echarts", async () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "new_widgets");
    const { container } = render(
      <WidgetRenderer widget={makeWidget({ type: "bar", visualizationOptions: { renderer: "echarts" } })} data={data} />
    );
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId("echarts-widget")).toBeTruthy();
    expect(initMock).toHaveBeenCalled();
    cleanup();

    vi.clearAllMocks();
    const { container: rechartsContainer } = render(
      <WidgetRenderer widget={makeWidget({ type: "bar", visualizationOptions: { renderer: "recharts" } })} data={data} />
    );
    expect(screen.queryByTestId("echarts-widget")).toBeNull();
    expect(rechartsContainer.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("keeps unsupported widgets on the legacy renderer in default mode", () => {
    vi.stubEnv("NEXT_PUBLIC_ECHARTS_RENDERER_MODE", "default");
    const { container } = render(<WidgetRenderer widget={makeWidget({ type: "scatter" })} data={data} />);
    expect(screen.queryByTestId("echarts-widget")).toBeNull();
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });
});
