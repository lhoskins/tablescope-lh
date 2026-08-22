import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { ItsmChart } from "./ItsmChart";
import type { ItsmChart as ItsmChartData } from "./types";

const { chartMock, initMock, useMock } = vi.hoisted(() => {
  const chartMock = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
  const initMock = vi.fn(() => chartMock);
  const useMock = vi.fn();
  return { chartMock, initMock, useMock };
});

vi.mock("echarts/core", () => ({ use: useMock, init: initMock }));

function baseChart(overrides: Partial<ItsmChartData> = {}): ItsmChartData {
  return {
    chartKey: "c1",
    title: "Monthly Revenue",
    chartType: "line",
    xAxisLabel: null,
    yAxisLabel: "Revenue",
    series: [{ name: "Revenue", x: ["2026-01", "2026-02"], y: [8_675_866.14, 9_120_300.5] }],
    categories: ["2026-01", "2026-02"],
    unit: null,
    ...overrides,
  };
}

function lastOption() {
  const call = chartMock.setOption.mock.calls.at(-1);
  return call?.[0] as { yAxis?: { axisLabel?: { formatter?: (v: number) => string } }; series: Array<{ label?: { formatter?: (p: { value?: unknown }) => string } }> };
}

describe("ItsmChart", () => {
  it("does not add an axis/label formatter when the chart has no visualizationOptions (ITSM presets)", () => {
    render(<ItsmChart chart={baseChart()} />);
    const option = lastOption();
    expect(option.yAxis?.axisLabel?.formatter).toBeUndefined();
  });

  it("scales the axis and data label to millions for an AI-Designer widget with unit=millions", () => {
    const chart = baseChart({
      chartType: "skinny_bar",
      visualizationOptions: { valueScale: "millions" },
    });
    render(<ItsmChart chart={chart} />);
    const option = lastOption();

    // skinny_bar is horizontal, so the VALUE axis is xAxis, not yAxis.
    const call = chartMock.setOption.mock.calls.at(-1)?.[0] as {
      xAxis?: { axisLabel?: { formatter?: (v: number) => string } };
      series: Array<{ label?: { formatter?: (p: { value?: unknown }) => string } }>;
    };
    expect(call.xAxis?.axisLabel?.formatter?.(8_675_866.14)).toBe("8.7M");
    expect(call.series[0].label?.formatter?.({ value: 8_675_866.14 })).toBe("8.7M");
  });

  it("scales the line chart's y-axis to millions with a currency symbol when both are set", () => {
    const chart = baseChart({
      visualizationOptions: { valueScale: "millions", yAxisFormat: "currency", currencySymbol: "€" },
    });
    render(<ItsmChart chart={chart} />);
    const option = lastOption();
    expect(option.yAxis?.axisLabel?.formatter?.(8_675_866.14)).toBe("€8.7M");
  });
});
