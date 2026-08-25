import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  InsightCard,
  TimeSeriesResponse,
} from "@/lib/api/home-intelligence";

import { InsightTimeSeriesChart } from "./insight-time-series-chart";

const response: TimeSeriesResponse = {
  insight_id: "insight-1",
  metric: {
    name: "Revenue",
    aggregation: "sum",
    is_rate_or_ratio: false,
    value_format: "currency",
  },
  interval: "month",
  range: "1y",
  timezone: "UTC",
  comparison_label: "Compared with the previous month",
  points: [
    {
      label: "2026-01",
      period_start: "2026-01-01",
      period_end: "2026-01-31",
      current_value: 100,
      previous_value: 80,
      percent_change_ratio: 0.25,
      percent_change_label: "+25.0%",
      comparison_status: "valid",
      partial: false,
      warnings: [],
    },
    {
      label: "2026-02",
      period_start: "2026-02-01",
      period_end: "2026-02-28",
      current_value: 90,
      previous_value: 100,
      percent_change_ratio: -0.1,
      percent_change_label: "-10.0%",
      comparison_status: "valid",
      partial: false,
      warnings: [],
    },
  ],
  calculation: {
    formula: "(current - previous) / previous",
    interval: "month",
    range: "1y",
    range_start: "2026-01-01",
    range_end: "2026-02-28",
    as_of: "2026-02-28",
    previous_periods_included: 1,
    notes: [],
  },
  warnings: [],
  eligible: true,
  source_grain: "month",
  supported_intervals: ["month"],
};

const card: InsightCard = {
  id: "card-1",
  insightId: "insight-1",
  projectId: "1",
  projectName: "Finance",
  projectColor: "#2563eb",
  insightType: "trend_revenue",
  severity: "trend",
  title: "Revenue trend",
  summary: "Revenue changed over time.",
  chart: {
    type: "line",
    title: "Revenue",
    data: {
      series: [
        { label: "2026-01", value: 100 },
        { label: "2026-02", value: 90 },
      ],
    },
  },
  callout: null,
  sources: { tables: ["revenue"], documents: [] },
  executedAt: "2026-02-28T00:00:00Z",
};

vi.mock("@/lib/hooks/use-insight-time-series", () => ({
  useInsightTimeSeries: () => ({ data: response, isLoading: false }),
}));

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartView: ({ chart }: { chart: { seriesLabels?: { value?: string } } }) => (
    <div data-testid="generic-chart">{chart.seriesLabels?.value}</div>
  ),
  OperationalInsightChartView: ({ chart }: { chart: { seriesLabels?: { value?: string } } }) => (
    <div data-testid="operational-chart">{chart.seriesLabels?.value}</div>
  ),
}));

describe("InsightTimeSeriesChart operational presentation", () => {
  it("uses ITSM for Value and preserves the existing % Change renderer and controls", async () => {
    const onViewChange = vi.fn();
    render(
      <InsightTimeSeriesChart
        card={card}
        projectId={1}
        presentation="operational"
        onViewChange={onViewChange}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Value" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.getByTestId("operational-chart").textContent).toBe("Revenue");

    fireEvent.click(screen.getByRole("button", { name: "% Change" }));

    expect(
      screen.getByRole("button", { name: "% Change" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.getByTestId("generic-chart").textContent).toBe(
      "% change in Revenue",
    );
    expect(screen.queryByTestId("operational-chart")).toBeNull();
    expect(screen.getByText("Calculation details")).toBeTruthy();
    await waitFor(() => {
      expect(onViewChange).toHaveBeenLastCalledWith({
        mode: "percent_change",
        interval: "month",
        range: "1y",
      });
    });
  });
});
