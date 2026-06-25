import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const post = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
}));

import {
  AIDashboardSuggestionsModal,
  type DashboardSuggestion,
} from "./ai-dashboard-suggestions-modal";

function suggestion(id: string, title: string): DashboardSuggestion {
  return {
    id,
    title,
    description: `${title} desc`,
    businessPurpose: "purpose",
    audience: "executive",
    widgets: [{ title: "w", chartType: "bar", businessQuestion: "q" }],
    kpis: ["Revenue"],
    dataSources: ["sales"],
    confidence: 0.9,
    qualityScore: 88,
    validationSummary: "ok",
  };
}

function renderModal(props: Partial<Parameters<typeof AIDashboardSuggestionsModal>[0]> = {}) {
  const client = new QueryClient();
  const onSaved = vi.fn();
  const notify = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AIDashboardSuggestionsModal
        open
        projectId="7"
        onClose={vi.fn()}
        onSaved={onSaved}
        notify={notify}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onSaved, notify };
}

describe("AIDashboardSuggestionsModal", () => {
  beforeEach(() => post.mockReset());

  it("generates and renders at least 3 suggestions", async () => {
    post.mockResolvedValueOnce({
      suggestions: [
        suggestion("a", "Revenue Overview"),
        suggestion("b", "Supplier Quality"),
        suggestion("c", "Delivery Performance"),
      ],
    });
    renderModal();

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() =>
      expect(screen.getByText("Revenue Overview")).toBeTruthy(),
    );
    expect(screen.getByText("Supplier Quality")).toBeTruthy();
    expect(screen.getByText("Delivery Performance")).toBeTruthy();
    expect(post).toHaveBeenCalledWith(
      "/api/ai/actions/suggest-dashboards",
      expect.objectContaining({ project_id: 7, desired_count: 3 }),
    );
  });

  it("saves a suggestion via the generate-and-save endpoint", async () => {
    post
      .mockResolvedValueOnce({ suggestions: [suggestion("a", "Revenue Overview")] })
      .mockResolvedValueOnce({ dashboard_id: 42, dashboard_name: "Revenue Overview" });
    const { onSaved } = renderModal();

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    await waitFor(() =>
      expect(screen.getByText("Revenue Overview")).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(42));
    expect(post).toHaveBeenLastCalledWith(
      "/api/ai/actions/save-dashboard-suggestion",
      expect.objectContaining({
        project_id: 7,
        suggestionId: "a",
        suggestion: expect.objectContaining({ title: "Revenue Overview" }),
      }),
    );
  });

  it("shows an empty-state message when no suggestions return", async () => {
    post.mockResolvedValueOnce({ suggestions: [] });
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    await waitFor(() =>
      expect(
        screen.getByText(/no dashboard suggestions could be generated/i),
      ).toBeTruthy(),
    );
  });
});
