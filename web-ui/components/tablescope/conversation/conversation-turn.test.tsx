import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TurnBubble } from "./conversation-turn";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";

vi.mock("@/components/dashboard/WidgetRenderer", () => ({
  WidgetRenderer: () => <div data-testid="widget" />,
}));

vi.mock("@/lib/insights/export-png", () => ({
  exportInsightCardPng: vi.fn(),
  insightPngFilename: () => "insight.png",
}));

function turn(overrides: Partial<ConversationTurn> = {}): ConversationTurn {
  return {
    id: 1,
    sequence: 1,
    user_message: "Why is material cost increasing?",
    intent_type: null,
    status: "success",
    assistant_message: "ok",
    sql: null,
    result: null,
    chart_config: null,
    explanation: null,
    error_code: null,
    matched_insight: null,
    ...overrides,
  };
}

describe("TurnBubble (Business/Project Insights shared conversation UI)", () => {
  it("renders the matched card's chart and breadcrumb when the backend falls back to it", () => {
    render(
      <TurnBubble
        turn={turn({
          assistant_message:
            "I couldn't build a live query for this question. I found an existing analysis that answers this: **Material cost on the rise**",
          matched_insight: {
            insightId: "mat-cost-001",
            projectId: 7,
            projectName: "Manufacturing",
            title: "Material cost on the rise",
            summary: "Weekly material cost has increased steadily.",
            chart: { type: "line", data: { rows: [{ period: "2026-01", value: 100 }] } },
            severity: "warning",
          },
        })}
      />,
    );

    expect(screen.getByText("Material cost on the rise")).toBeInTheDocument();
    expect(screen.getByTestId("widget")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /explore full analysis/i }),
    ).toHaveAttribute("href", "/business-insight/analysis/mat-cost-001");
  });

  it("renders no matched-insight block when the turn has none", () => {
    render(<TurnBubble turn={turn()} />);
    expect(screen.queryByText(/explore full analysis/i)).not.toBeInTheDocument();
  });
});
