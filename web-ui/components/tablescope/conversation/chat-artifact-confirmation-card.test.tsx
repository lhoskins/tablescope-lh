import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";

const { decideArtifactProposal } = vi.hoisted(() => ({
  decideArtifactProposal: vi.fn(),
}));

vi.mock("@/lib/api/conversational-analytics", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@/lib/api/conversational-analytics",
  );
  return { ...actual, decideArtifactProposal };
});

import { ChatArtifactConfirmationCard } from "./chat-artifact-confirmation-card";

function turn(kind: "query" | "dashboard" = "query"): ConversationTurn {
  return {
    id: 8,
    sequence: 1,
    user_message: `Create a ${kind} for monthly sales`,
    intent_type: `create_${kind}`,
    status: "success",
    assistant_message: "Review before creating.",
    sql: kind === "query" ? "SELECT month, SUM(sales) FROM sales GROUP BY month" : null,
    result: null,
    chart_config: null,
    explanation: null,
    artifact_proposal: {
      kind,
      status: "pending",
      title: `Monthly sales ${kind}`,
      prompt: `Create a ${kind} for monthly sales`,
      description: "Review this grounded proposal before creating it.",
      dataSources: kind === "query" ? ["sales"] : [],
      dashboardDesign:
        kind === "dashboard"
          ? {
              supportStatus: "fully_supported",
              widgets: [
                { title: "Sales by month", chartType: "bar", businessQuestion: "How do monthly sales trend?" },
                { title: "Top regions", chartType: "pie", businessQuestion: "" },
              ],
            }
          : null,
    },
    error_code: null,
    matched_insight: null,
    attachments: [],
  };
}

function renderCard(artifactTurn: ConversationTurn) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ChatArtifactConfirmationCard
        conversationId={3}
        projectId="42"
        turn={artifactTurn}
      />
    </QueryClientProvider>,
  );
}

describe("ChatArtifactConfirmationCard", () => {
  beforeEach(() => decideArtifactProposal.mockReset());

  it("saves a query only after explicit confirmation", async () => {
    const accepted = turn("query");
    accepted.artifact_proposal = {
      ...accepted.artifact_proposal!,
      status: "accepted",
      assetId: 19,
      assetUrl: "/projects/42/queries",
    };
    decideArtifactProposal.mockResolvedValue({ conversation_id: 3, turn: accepted });

    renderCard(turn("query"));
    expect(screen.getByText("Pending approval")).toBeInTheDocument();
    expect(screen.getByText(/Grounded in sales/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save query/i }));

    await waitFor(() =>
      expect(decideArtifactProposal).toHaveBeenCalledWith(3, 8, {
        decision: "accept",
        artifact_kind: "query",
      }),
    );
    expect(await screen.findByText("Created")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open query/i })).toHaveAttribute(
      "href",
      "/projects/42/queries",
    );
  });

  it("previews the proposed charts and creates the dashboard directly on Create -- no designer modal", async () => {
    const accepted = turn("dashboard");
    accepted.artifact_proposal = {
      ...accepted.artifact_proposal!,
      status: "accepted",
      assetId: 91,
      assetUrl: "/projects/42/dashboards/91",
    };
    decideArtifactProposal.mockResolvedValue({ conversation_id: 3, turn: accepted });

    renderCard(turn("dashboard"));
    expect(screen.getByText("Sales by month")).toBeInTheDocument();
    expect(screen.getByText(/How do monthly sales trend\?/)).toBeInTheDocument();
    expect(screen.getByText("Top regions")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() =>
      expect(decideArtifactProposal).toHaveBeenCalledWith(3, 8, {
        decision: "accept",
        artifact_kind: "dashboard",
      }),
    );
    expect(await screen.findByText("Created")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open dashboard/i })).toHaveAttribute(
      "href",
      "/projects/42/dashboards/91",
    );
  });

  it("shows a partial-support caveat when the design doesn't fully cover the request", () => {
    const partial = turn("dashboard");
    partial.artifact_proposal!.dashboardDesign!.supportStatus = "partially_supported";
    renderCard(partial);
    expect(
      screen.getByText(/Some requested data isn't fully available yet/),
    ).toBeInTheDocument();
  });
});
