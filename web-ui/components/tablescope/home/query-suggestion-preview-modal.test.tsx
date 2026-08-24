import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { InsightChart } from "@/lib/api/home-intelligence";

const { runDatasourceSql } = vi.hoisted(() => ({
  runDatasourceSql: vi.fn(),
}));
const { saveQuerySuggestion, createHomePin } = vi.hoisted(() => ({
  saveQuerySuggestion: vi.fn(),
  createHomePin: vi.fn(),
}));

vi.mock("@/lib/api/data-source-builder", () => ({
  runDatasourceSql,
}));

vi.mock("@/lib/api/home-intelligence", () => ({
  saveQuerySuggestion,
}));

vi.mock("@/lib/api/home-pins", () => ({
  createHomePin,
}));

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: ({ chart }: { chart: InsightChart }) => (
    <div data-testid="chart">{chart.type}</div>
  ),
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: vi.fn(() => ({ data: [] })),
}));

vi.mock("@/components/tablescope/home/save-insight-to-dashboard-modal", () => ({
  SaveInsightToDashboardModal: vi.fn(() => <div data-testid="save-modal" />),
}));

import { QuerySuggestionPreviewModal, evaluateChartQuality } from "./query-suggestion-preview-modal";

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <QuerySuggestionPreviewModal
        open
        projectId={42}
        title="Late shipments"
        description="Shipments after due date"
        sql="SELECT supplier, COUNT(*) AS late FROM shipments WHERE due > '2024-01-01T00:00:00' GROUP BY supplier"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

const RESULT = {
  columns: ["supplier", "late"],
  rows: [{ supplier: "Acme", late: 3 }],
};

describe("QuerySuggestionPreviewModal", () => {
  beforeEach(() => {
    runDatasourceSql.mockReset();
    saveQuerySuggestion.mockReset().mockResolvedValue({
      query_id: 77,
      name: "Late shipments",
      status: "saved",
      sql_text: "SELECT 1",
    });
    createHomePin.mockReset().mockResolvedValue({ id: 88 });
  });

  it("executes the query and renders a chart preview", async () => {
    runDatasourceSql.mockResolvedValue(RESULT);
    renderModal();
    expect(await screen.findByTestId("chart")).toBeTruthy();
    fireEvent.click(screen.getByText(/Preview data/));
    expect(screen.getByText("Acme")).toBeTruthy();
  });

  it("shows the generated SQL on request", async () => {
    runDatasourceSql.mockResolvedValue(RESULT);
    renderModal();
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByText(/^SQL$/));
    await waitFor(() =>
      expect(screen.getByText(/due > '2024-01-01T00:00:00'/)).toBeTruthy(),
    );
  });

  it("renders an actionable error when execution fails", async () => {
    runDatasourceSql.mockRejectedValue(new Error("Timestamp parse error"));
    renderModal();
    expect(
      await screen.findByText(/The query could not be executed/),
    ).toBeTruthy();
    expect(screen.getByText("Timestamp parse error")).toBeTruthy();
  });

  it("renders an Add to Dashboard button after the query succeeds", async () => {
    runDatasourceSql.mockResolvedValue(RESULT);
    renderModal();
    await screen.findByTestId("chart");
    const btn = screen.getByRole("button", { name: /Add to Dashboard/i });
    expect(btn).toBeTruthy();
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it("saves the query and pins the selected chart to Home", async () => {
    runDatasourceSql.mockResolvedValue(RESULT);
    renderModal();
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByRole("button", { name: /Add selected chart to Home/i }));

    await waitFor(() => expect(saveQuerySuggestion).toHaveBeenCalled());
    await waitFor(() =>
      expect(createHomePin).toHaveBeenCalledWith(
        expect.objectContaining({
          pin_type: "live_widget",
          project_id: 42,
          config: expect.objectContaining({
            widget: expect.objectContaining({ dataSource: { kind: "query", queryId: 77 } }),
          }),
        }),
      ),
    );
  });
});

describe("evaluateChartQuality", () => {
  const columns = ["month", "revenue"];
  const rows = [{ month: "Jan", revenue: 10 }, { month: "Feb", revenue: null }];

  it("passes compatibility when every required field is a real column", () => {
    const { compatibility } = evaluateChartQuality({ type: "bar", xField: "month", yField: "revenue" }, columns, rows);
    expect(compatibility).toEqual({ ok: true, label: "All required fields" });
  });

  it("fails compatibility and names the missing field", () => {
    const { compatibility } = evaluateChartQuality({ type: "bar", xField: "month", yField: "profit" }, columns, rows);
    expect(compatibility.ok).toBe(false);
    expect(compatibility.label).toContain("profit");
  });

  it("reports how many rows actually carry the measured value", () => {
    const { dataQuality } = evaluateChartQuality({ type: "bar", xField: "month", yField: "revenue" }, columns, rows);
    expect(dataQuality).toEqual({ ok: true, label: "1/2 rows with data" });
  });

  it("flags data quality as failing when no row has the measured value", () => {
    const allNull = [{ month: "Jan", revenue: null }, { month: "Feb", revenue: null }];
    const { dataQuality } = evaluateChartQuality({ type: "bar", xField: "month", yField: "revenue" }, columns, allNull);
    expect(dataQuality.ok).toBe(false);
  });

  it("flags an empty preview as failing data quality", () => {
    const { dataQuality } = evaluateChartQuality({ type: "bar", xField: "month", yField: "revenue" }, columns, []);
    expect(dataQuality).toEqual({ ok: false, label: "No preview rows returned" });
  });
});
