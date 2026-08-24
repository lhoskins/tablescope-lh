import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { OperationalInsightGrid } from "./OperationalInsightGrid";
import type { WidgetConfig } from "./types";

const { chartMock, initMock, useMock } = vi.hoisted(() => {
  const chartMock = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
  const initMock = vi.fn(() => chartMock);
  const useMock = vi.fn();
  return { chartMock, initMock, useMock };
});

vi.mock("echarts/core", () => ({ use: useMock, init: initMock }));

function kpiWidget(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
  return {
    id: "kpi-1",
    type: "kpi",
    title: "Total Revenue",
    dataSource: { kind: "query", queryId: 1 },
    xColumn: "",
    yColumn: "revenue",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    colSpan: 4,
    position: 0,
    ...overrides,
  };
}

function chartWidget(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
  return {
    id: "chart-1",
    type: "bar",
    title: "Monthly Revenue",
    dataSource: { kind: "query", queryId: 1 },
    xColumn: "month",
    yColumn: "revenue",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    colSpan: 6,
    position: 1,
    ...overrides,
  };
}

const noop = vi.fn();

describe("OperationalInsightGrid", () => {
  it("renders KPI and chart widgets in position order", () => {
    const widgets = [
      chartWidget({ id: "chart-1", title: "Monthly Revenue", position: 1 }),
      kpiWidget({ id: "kpi-1", title: "Total Revenue", position: 0 }),
    ];
    render(
      <OperationalInsightGrid
        widgets={widgets}
        widgetData={{}}
        operationalWidgets={[]}
        onEditWidget={noop}
        onElementClick={noop}
      />,
    );
    const headings = screen.getAllByText(/Total Revenue|Monthly Revenue/);
    expect(headings[0]).toHaveTextContent("Total Revenue");
    expect(headings[1]).toHaveTextContent("Monthly Revenue");
  });

  it("shows no resize handle when not editing", () => {
    render(
      <OperationalInsightGrid
        widgets={[kpiWidget(), chartWidget()]}
        widgetData={{}}
        operationalWidgets={[]}
        onEditWidget={noop}
        onElementClick={noop}
      />,
    );
    expect(screen.queryByTitle("Drag to resize")).toBeNull();
  });

  it("drags a KPI card's resize handle and reports the new width", () => {
    const onLayoutChange = vi.fn();
    render(
      <OperationalInsightGrid
        widgets={[kpiWidget()]}
        widgetData={{}}
        operationalWidgets={[]}
        editingLayout
        onEditWidget={noop}
        onElementClick={noop}
        onLayoutChange={onLayoutChange}
      />,
    );
    const grid = document.querySelector('[class*="kpiGrid"]') as HTMLElement;
    vi.spyOn(grid, "getBoundingClientRect").mockReturnValue({
      width: 1200,
    } as DOMRect);

    const handle = screen.getByTitle("Drag to resize");
    fireEvent.mouseDown(handle, { clientX: 0, clientY: 0 });
    // Grid is 1200px wide across 12 columns (~100px/column stride incl. gap)
    // -- dragging 300px right should grow the span by roughly 3 columns.
    fireEvent.mouseMove(window, { clientX: 300, clientY: 0 });
    fireEvent.mouseUp(window);

    expect(onLayoutChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "kpi-1",
        visualizationOptions: expect.objectContaining({ gridSpan: expect.any(Number) }),
      }),
    ]);
    const patch = onLayoutChange.mock.calls.at(-1)?.[0][0].visualizationOptions.gridSpan as number;
    expect(patch).toBeGreaterThan(4);
  });

  it("drags a KPI card's resize handle vertically and reports the new height", () => {
    const onLayoutChange = vi.fn();
    render(
      <OperationalInsightGrid
        widgets={[kpiWidget()]}
        widgetData={{}}
        operationalWidgets={[]}
        editingLayout
        onEditWidget={noop}
        onElementClick={noop}
        onLayoutChange={onLayoutChange}
      />,
    );
    const grid = document.querySelector('[class*="kpiGrid"]') as HTMLElement;
    vi.spyOn(grid, "getBoundingClientRect").mockReturnValue({ width: 1200 } as DOMRect);

    const handle = screen.getByTitle("Drag to resize");
    fireEvent.mouseDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.mouseMove(window, { clientX: 0, clientY: 60 });
    fireEvent.mouseUp(window);

    const options = onLayoutChange.mock.calls.at(-1)?.[0][0].visualizationOptions;
    expect(options.gridHeightPx).toBeGreaterThan(96);
  });

  it("does not stretch a KPI card to a neighboring chart's height", () => {
    const widgets = [
      kpiWidget({ id: "kpi-1", title: "Total Revenue", position: 0 }),
      chartWidget({ id: "chart-1", title: "Monthly Revenue", position: 1 }),
    ];
    render(
      <OperationalInsightGrid
        widgets={widgets}
        widgetData={{}}
        operationalWidgets={[]}
        onEditWidget={noop}
        onElementClick={noop}
      />,
    );
    const grid = document.querySelector('[class*="kpiGrid"]') as HTMLElement;
    expect(grid.style.alignItems).toBe("start");

    const kpiCard = screen.getByText("Total Revenue").closest("div.relative") as HTMLElement;
    expect(kpiCard.style.height).toBe("96px");
  });

  it("drags a chart's resize handle and reports the new width and height", () => {
    const onLayoutChange = vi.fn();
    render(
      <OperationalInsightGrid
        widgets={[chartWidget()]}
        widgetData={{}}
        operationalWidgets={[]}
        editingLayout
        onEditWidget={noop}
        onElementClick={noop}
        onLayoutChange={onLayoutChange}
      />,
    );
    const grid = document.querySelector('[class*="kpiGrid"]') as HTMLElement;
    vi.spyOn(grid, "getBoundingClientRect").mockReturnValue({
      width: 1200,
    } as DOMRect);

    const handle = screen.getByTitle("Drag to resize");
    fireEvent.mouseDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.mouseMove(window, { clientX: -200, clientY: 80 });
    fireEvent.mouseUp(window);

    expect(onLayoutChange).toHaveBeenCalledTimes(1);
    const options = onLayoutChange.mock.calls.at(-1)?.[0][0].visualizationOptions;
    expect(options.gridSpan).toBeLessThan(12);
    expect(options.gridHeightPx).toBeGreaterThan(320);
  });

  it("reorders widgets via drag-and-drop and persists the new position", () => {
    const onLayoutChange = vi.fn();
    const widgets = [kpiWidget({ id: "a", title: "A", position: 0 }), kpiWidget({ id: "b", title: "B", position: 1 })];
    render(
      <OperationalInsightGrid
        widgets={widgets}
        widgetData={{}}
        operationalWidgets={[]}
        editingLayout
        onEditWidget={noop}
        onElementClick={noop}
        onLayoutChange={onLayoutChange}
      />,
    );
    const cardA = screen.getByText("A").closest("[draggable]") as HTMLElement;
    const cardB = screen.getByText("B").closest("[draggable]") as HTMLElement;
    fireEvent.dragStart(cardA);
    fireEvent.drop(cardB);

    const saved = onLayoutChange.mock.calls.at(-1)?.[0] as WidgetConfig[];
    expect(saved.map((w) => w.id)).toEqual(["b", "a"]);
    expect(saved.map((w) => w.position)).toEqual([0, 1]);
  });

  it("does not allow dragging when not in edit mode", () => {
    const widgets = [kpiWidget({ id: "a", title: "A" })];
    render(
      <OperationalInsightGrid
        widgets={widgets}
        widgetData={{}}
        operationalWidgets={[]}
        onEditWidget={noop}
        onElementClick={noop}
      />,
    );
    const cardA = screen.getByText("A").closest("div[draggable]") as HTMLElement;
    expect(cardA.getAttribute("draggable")).toBe("false");
  });
});
