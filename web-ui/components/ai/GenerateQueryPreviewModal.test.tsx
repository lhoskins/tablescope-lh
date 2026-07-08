import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { generateQueryPreview, saveQuery } = vi.hoisted(() => ({
  generateQueryPreview: vi.fn(),
  saveQuery: vi.fn(),
}));

vi.mock("@/lib/api/ai-actions", () => ({
  aiActionsApi: {
    generateQueryPreview: (...a: unknown[]) => generateQueryPreview(...a),
    saveQuery: (...a: unknown[]) => saveQuery(...a),
  },
}));

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div data-testid="chart" />,
}));

import { GenerateQueryPreviewModal } from "./GenerateQueryPreviewModal";

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onSaved = vi.fn();
  const notify = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <GenerateQueryPreviewModal
        open
        projectId="42"
        question="Late shipments by supplier"
        title="Late Shipments"
        description="Which suppliers ship late?"
        onClose={() => {}}
        onSaved={onSaved}
        notify={notify}
      />
    </QueryClientProvider>,
  );
  return { onSaved, notify };
}

const PREVIEW = {
  title: "Late Shipments",
  description: "Which suppliers ship late?",
  sql: "SELECT supplier, late FROM shipments",
  columns: ["supplier", "late"],
  rows: [{ supplier: "A", late: 4 }],
  suggestedVisualization: { type: "bar", xField: "supplier", yField: "late" },
  dataSourcesUsed: ["shipments_csv"],
  explanation: "",
  status: "success" as const,
  error: null,
};

describe("GenerateQueryPreviewModal", () => {
  beforeEach(() => {
    generateQueryPreview.mockReset();
    saveQuery.mockReset();
  });

  it("previews the generated query then saves it", async () => {
    generateQueryPreview.mockResolvedValue(PREVIEW);
    saveQuery.mockResolvedValue({
      action: "save_query",
      status: "saved",
      query_id: 9,
      name: "Late Shipments",
      sql_text: PREVIEW.sql,
    });
    const { onSaved, notify } = renderModal();

    // Title + preview rows render.
    expect(await screen.findByText("Late Shipments")).toBeTruthy();
    expect(screen.getByText("supplier")).toBeTruthy();

    const saveBtn = await screen.findByRole("button", { name: /save query/i });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(saveQuery).toHaveBeenCalled());
    expect(onSaved).toHaveBeenCalledWith(9);
    expect(notify).toHaveBeenCalledWith(
      expect.stringContaining("Saved query"),
      "success",
    );
  });

  it("shows an inline error when generation fails", async () => {
    generateQueryPreview.mockResolvedValue({
      ...PREVIEW,
      sql: "",
      columns: [],
      rows: [],
      status: "generation_error",
      error: "No data source available",
    });
    renderModal();
    expect(await screen.findByText(/Couldn't generate this query/i)).toBeTruthy();
    expect(screen.getByText("No data source available")).toBeTruthy();
  });
});
