import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { runDatasourceSql, saveQuerySuggestion } = vi.hoisted(() => ({
  runDatasourceSql: vi.fn(),
  saveQuerySuggestion: vi.fn(),
}));

vi.mock("@/lib/api/data-source-builder", () => ({
  runDatasourceSql: (...a: unknown[]) => runDatasourceSql(...a),
}));

vi.mock("@/lib/api/home-intelligence", () => ({
  saveQuerySuggestion: (...a: unknown[]) => saveQuerySuggestion(...a),
}));

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div data-testid="chart" />,
}));

import { QuerySuggestionPreviewModal } from "./query-suggestion-preview-modal";

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <QuerySuggestionPreviewModal
        open
        projectId={7}
        title="Assets by department"
        description="How many assets per department?"
        sql='SELECT "Dept", COUNT(*) AS n FROM "assets" GROUP BY "Dept"'
        onClose={() => {}}
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { onSaved };
}

describe("QuerySuggestionPreviewModal", () => {
  beforeEach(() => {
    runDatasourceSql.mockReset();
    saveQuerySuggestion.mockReset();
  });

  it("runs the suggestion SQL then saves only from the preview", async () => {
    runDatasourceSql.mockResolvedValue({
      columns: ["Dept", "n"],
      rows: [
        { Dept: "IT", n: 12 },
        { Dept: "HR", n: 4 },
      ],
    });
    saveQuerySuggestion.mockResolvedValue({ name: "Assets by department", status: "saved" });
    const { onSaved } = renderModal();

    // The SQL is executed with no added LIMIT (raw sql path).
    await waitFor(() => expect(runDatasourceSql).toHaveBeenCalled());
    expect(runDatasourceSql).toHaveBeenCalledWith({
      sql: 'SELECT "Dept", COUNT(*) AS n FROM "assets" GROUP BY "Dept"',
      project_id: 7,
    });

    // Result table renders the returned rows.
    expect(await screen.findByText("IT")).toBeTruthy();

    // SQL is hidden until toggled.
    expect(screen.queryByText(/GROUP BY/)).toBeNull();
    fireEvent.click(screen.getByText("Show SQL"));
    expect(await screen.findByText(/GROUP BY/)).toBeTruthy();

    const saveBtn = screen.getByRole("button", { name: /save query/i });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(saveQuerySuggestion).toHaveBeenCalled());
    expect(saveQuerySuggestion).toHaveBeenCalledWith({
      project_id: 7,
      name: "Assets by department",
      description: "How many assets per department?",
      sql_text: 'SELECT "Dept", COUNT(*) AS n FROM "assets" GROUP BY "Dept"',
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("shows an inline error when the query fails", async () => {
    runDatasourceSql.mockRejectedValue(new Error("Query failed: TEIID30070"));
    renderModal();
    expect(
      await screen.findByText(/could not be executed/i),
    ).toBeTruthy();
    expect(screen.getByText(/TEIID30070/)).toBeTruthy();
  });
});
