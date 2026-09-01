import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { generateQueryPreview, saveQuery } = vi.hoisted(() => ({
  generateQueryPreview: vi.fn(),
  saveQuery: vi.fn(),
}));

vi.mock("@/lib/api/ai-actions", () => ({
  aiActionsApi: {
    generateQueryPreview: (...args: unknown[]) => generateQueryPreview(...args),
    saveQuery: (...args: unknown[]) => saveQuery(...args),
  },
}));

import { AIQueryDesigner } from "./ai-query-designer";

const PREVIEW = {
  title: "Monthly Backlog vs Revenue",
  description: "Compare monthly backlog and revenue.",
  sql: "SELECT month, SUM(backlog) AS backlog FROM orders GROUP BY month",
  columns: ["month", "backlog"],
  rows: [{ month: "2026-01", backlog: 100 }],
  suggestedVisualization: { type: "line" },
  dataSourcesUsed: ["orders"],
  explanation: "",
  status: "success" as const,
  error: null,
};

function renderDesigner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const notify = vi.fn();
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AIQueryDesigner
        open
        projectId="42"
        onClose={onClose}
        onSaved={onSaved}
        notify={notify}
      />
    </QueryClientProvider>,
  );
  return { notify, onSaved, onClose };
}

describe("AIQueryDesigner", () => {
  beforeEach(() => {
    generateQueryPreview.mockReset();
    saveQuery.mockReset();
  });

  it("uses plain-language instruction boxes without currency or folder creation context", () => {
    renderDesigner();

    expect(screen.getByLabelText("SUM / aggregate instructions")).toBeInTheDocument();
    expect(screen.getByLabelText("GROUP BY instructions")).toBeInTheDocument();
    expect(screen.getByLabelText("CASE instructions")).toBeInTheDocument();
    expect(screen.getByLabelText("FILTER instructions")).toBeInTheDocument();
    expect(screen.getByLabelText("SORT instructions")).toBeInTheDocument();
    expect(screen.queryByText(/^Currency$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/save to folder/i)).not.toBeInTheDocument();
  });

  it("disables batch analysis until at least one business request is provided", () => {
    renderDesigner();
    const analyze = screen.getByRole("button", {
      name: /analyze data & propose queries/i,
    });
    expect(analyze).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Business request"), {
      target: { value: "Compare backlog with revenue by month" },
    });
    expect(analyze).not.toBeDisabled();
  });

  it("generates, reviews, and saves multiple queries as one isolated batch", async () => {
    generateQueryPreview.mockImplementation(
      async (_projectId: string, _question: string, title?: string) => ({
        ...PREVIEW,
        title: title || PREVIEW.title,
      }),
    );
    saveQuery
      .mockResolvedValueOnce({ query_id: 101, name: "Monthly Backlog vs Revenue" })
      .mockResolvedValueOnce({ query_id: 102, name: "Late Orders" });
    const { onSaved, notify } = renderDesigner();

    fireEvent.change(screen.getByLabelText("Query name (optional)"), {
      target: { value: "Monthly Backlog vs Revenue" },
    });
    fireEvent.change(screen.getByLabelText("Business request"), {
      target: { value: "Join orders and revenue by sales_order_id" },
    });
    fireEvent.change(screen.getByLabelText("SUM / aggregate instructions"), {
      target: { value: "Sum backlog and recognized revenue" },
    });
    fireEvent.change(screen.getByLabelText("GROUP BY instructions"), {
      target: { value: "Group by order month" },
    });
    fireEvent.change(screen.getByLabelText("CASE instructions"), {
      target: { value: "Label backlog over 30 days Critical" },
    });
    fireEvent.change(screen.getByLabelText("FILTER instructions"), {
      target: { value: "Only open orders" },
    });
    fireEvent.change(screen.getByLabelText("SORT instructions"), {
      target: { value: "Sort month ascending" },
    });
    fireEvent.change(screen.getByPlaceholderText("Example: Site, Region, Team"), {
      target: { value: "Region" },
    });

    fireEvent.click(screen.getByRole("button", { name: /add another query/i }));
    const nameFields = screen.getAllByLabelText("Query name (optional)");
    const requestFields = screen.getAllByLabelText("Business request");
    fireEvent.change(nameFields[nameFields.length - 1], {
      target: { value: "Late Orders" },
    });
    fireEvent.change(requestFields[requestFields.length - 1], {
      target: { value: "Show overdue open orders and days late" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /analyze data & propose queries/i }),
    );

    expect(await screen.findByText("Review query batch")).toBeInTheDocument();
    expect(generateQueryPreview).toHaveBeenCalledTimes(2);
    const firstQuestion = String(generateQueryPreview.mock.calls[0][1]);
    expect(firstQuestion).toContain("SUM / aggregate: Sum backlog and recognized revenue");
    expect(firstQuestion).toContain("GROUP BY: Group by order month");
    expect(firstQuestion).toContain("CASE: Label backlog over 30 days Critical");
    expect(firstQuestion).toContain("FILTER: Only open orders");
    expect(firstQuestion).toContain("SORT: Sort month ascending");
    expect(firstQuestion).toContain("Primary dimension: Region");
    expect(firstQuestion).toContain("Validate join keys and cardinality");

    fireEvent.click(
      screen.getByRole("button", { name: /validate & create 2 selected queries/i }),
    );

    expect(await screen.findByText("Query batch complete")).toBeInTheDocument();
    expect(saveQuery).toHaveBeenCalledTimes(2);
    expect(onSaved).toHaveBeenNthCalledWith(1, 101);
    expect(onSaved).toHaveBeenNthCalledWith(2, 102);
    expect(notify).toHaveBeenCalledWith("Saved 2 queries", "success");
  });

  it("keeps ready queries selectable when another query fails generation", async () => {
    generateQueryPreview
      .mockResolvedValueOnce(PREVIEW)
      .mockResolvedValueOnce({
        ...PREVIEW,
        title: "Ambiguous Query",
        sql: "",
        rows: [],
        columns: [],
        status: "generation_error",
        error: "Unable to identify the requested source",
      });
    renderDesigner();

    fireEvent.change(screen.getByLabelText("Business request"), {
      target: { value: "Monthly backlog" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add another query/i }));
    const requestFields = screen.getAllByLabelText("Business request");
    fireEvent.change(requestFields[requestFields.length - 1], {
      target: { value: "Ambiguous request" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /analyze data & propose queries/i }),
    );

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /validate & create 1 selected query/i }),
    ).not.toBeDisabled();
    await waitFor(() => expect(generateQueryPreview).toHaveBeenCalledTimes(2));
  });
});
