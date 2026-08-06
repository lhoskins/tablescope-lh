import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getRecent = vi.fn();

vi.mock("@/lib/api/conversational-analytics", () => ({
  getRecentProjectConversations: (...args: unknown[]) => getRecent(...args),
}));

import { AiConversationsCard } from "./ai-conversations-card";

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AiConversationsCard projectId="7" />
    </QueryClientProvider>,
  );
}

function item(n: number) {
  return {
    conversation_id: 11,
    turn_id: n,
    surface: "project_insights",
    question_preview: `Question ${n}`,
    result_preview: `Result ${n}`,
    result_type: "text",
    completed_at: new Date().toISOString(),
  };
}

describe("AiConversationsCard", () => {
  beforeEach(() => {
    getRecent.mockReset();
  });

  it("renders the heading and one accessible link per conversation", async () => {
    getRecent.mockResolvedValue({
      project_id: 7,
      items: [item(1), item(2), item(3), item(4)],
    });
    renderCard();

    expect(
      screen.getByRole("heading", { name: "AI Assistant conversations" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Project activity")).not.toBeInTheDocument();

    const rows = await screen.findAllByRole("link", {
      name: /Open AI Assistant conversation/,
    });
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveAttribute(
      "href",
      "/ai?conversation=11&projectId=7&turn=1&from=project-overview",
    );
    expect(screen.getByText("Result 1")).toBeInTheDocument();
  });

  it("shows skeleton rows while loading", () => {
    getRecent.mockReturnValue(new Promise(() => {}));
    renderCard();
    expect(screen.getAllByTestId("conversation-skeleton")).toHaveLength(4);
  });

  it("shows the empty state when the project has no conversations", async () => {
    getRecent.mockResolvedValue({ project_id: 7, items: [] });
    renderCard();
    expect(
      await screen.findByText("No project conversations yet"),
    ).toBeInTheDocument();
  });

  it("localizes errors to the panel and retries", async () => {
    getRecent.mockRejectedValueOnce(new Error("boom"));
    renderCard();

    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByText("Unable to load conversations")).toBeInTheDocument();

    getRecent.mockResolvedValue({ project_id: 7, items: [item(9)] });
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("Question 9")).toBeInTheDocument());
  });

  it("links View all to the project-filtered AI Assistant", async () => {
    getRecent.mockResolvedValue({ project_id: 7, items: [] });
    renderCard();
    const viewAll = screen.getByRole("link", {
      name: /View all project conversations/,
    });
    expect(viewAll).toHaveAttribute("href", "/ai?projectId=7&from=project-overview");
  });
});
