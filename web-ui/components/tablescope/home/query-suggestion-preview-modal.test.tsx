import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { InsightChart } from "@/lib/api/home-intelligence";

const { runDatasourceSql } = vi.hoisted(() => ({
  runDatasourceSql: vi.fn(),
}));

vi.mock("@/lib/api/data-source-builder", () => ({
  runDatasourceSql,
}));

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: ({ chart }: { chart: InsightChart }) => (
    <div data-testid="chart">{chart.type}</div>
  ),
}));

import { QuerySuggestionPreviewModal } from "./query-suggestion-preview-modal";

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
  });

  it("executes the query and renders a chart preview", async () => {
    runDatasourceSql.mockResolvedValue(RESULT);
    renderModal();
    expect(await screen.findByTestId("chart")).toBeTruthy();
    expect(screen.getByText("Acme")).toBeTruthy();
  });

  it("shows the generated SQL on request", async () => {
    runDatasourceSql.mockResolvedValue(RESULT);
    renderModal();
    await screen.findByTestId("chart");
    fireEvent.click(screen.getByText(/Show SQL/));
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
});
