import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { askAndRun, saveQuery } = vi.hoisted(() => ({
  askAndRun: vi.fn(),
  saveQuery: vi.fn(),
}));

vi.mock("@/lib/api/ai-actions", () => ({
  aiActionsApi: {
    askAndRun: (...a: unknown[]) => askAndRun(...a),
    saveQuery: (...a: unknown[]) => saveQuery(...a),
  },
}));

// The chart renderer pulls in recharts; stub it so the modal test stays fast.
vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div data-testid="chart" />,
}));

import { AIQuestionResultModal } from "./AIQuestionResultModal";

function renderModal(props: Partial<Parameters<typeof AIQuestionResultModal>[0]> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onOpenAssistant = vi.fn();
  const notify = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AIQuestionResultModal
        open
        projectId="42"
        question="What is the defect rate per supplier?"
        onClose={() => {}}
        onOpenAssistant={onOpenAssistant}
        notify={notify}
        {...(props as Record<string, unknown>)}
      />
    </QueryClientProvider>,
  );
  return { onOpenAssistant, notify };
}

const SUCCESS = {
  question: "What is the defect rate per supplier?",
  sql: "SELECT supplier, defects FROM q",
  columns: ["supplier", "defects"],
  rows: [{ supplier: "A", defects: 3 }],
  suggestedVisualization: { type: "bar", xField: "supplier", yField: "defects" },
  explanation: "Computed from the quality table.",
  dataSourcesUsed: ["quality_csv"],
  status: "success" as const,
  error: null,
};

describe("AIQuestionResultModal", () => {
  beforeEach(() => {
    askAndRun.mockReset();
    saveQuery.mockReset();
  });

  it("renders results and the SQL toggle on success", async () => {
    askAndRun.mockResolvedValue(SUCCESS);
    renderModal();
    expect(await screen.findByText("Computed from the quality table.")).toBeTruthy();
    // Result table rendered with the executed rows.
    expect(screen.getByText("supplier")).toBeTruthy();
    expect(screen.getByText("A")).toBeTruthy();
    // SQL hidden by default behind a toggle.
    expect(screen.queryByText(/SELECT supplier/)).toBeNull();
    fireEvent.click(screen.getByText("Show SQL"));
    expect(await screen.findByText(/SELECT supplier, defects/)).toBeTruthy();
  });

  it("shows a friendly error and Open in AI Assistant on generation failure", async () => {
    askAndRun.mockResolvedValue({
      ...SUCCESS,
      sql: "",
      columns: [],
      rows: [],
      status: "generation_error",
      error: "AI server unreachable",
    });
    const { onOpenAssistant } = renderModal();
    expect(
      await screen.findByText(/Couldn't build a query/i),
    ).toBeTruthy();
    const btn = screen.getByRole("button", { name: /open in ai assistant/i });
    fireEvent.click(btn);
    expect(onOpenAssistant).toHaveBeenCalledWith(
      "What is the defect rate per supplier?",
    );
  });

  it("saves the query when Save Query is clicked", async () => {
    askAndRun.mockResolvedValue(SUCCESS);
    saveQuery.mockResolvedValue({
      action: "save_query",
      status: "saved",
      query_id: 7,
      name: "What is the defect rate per supplier",
      sql_text: SUCCESS.sql,
    });
    const { notify } = renderModal();
    const saveBtn = await screen.findByRole("button", { name: /save query/i });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(saveQuery).toHaveBeenCalled());
    expect(notify).toHaveBeenCalledWith(
      expect.stringContaining("Saved query"),
      "success",
    );
  });
});
