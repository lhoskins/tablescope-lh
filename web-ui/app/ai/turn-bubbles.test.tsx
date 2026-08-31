import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TurnBubbles } from "./turn-bubbles";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";

vi.mock("./turn-result", () => ({
  TurnResult: () => <div data-testid="turn-result" />,
}));

vi.mock("@/components/tablescope/conversation/matched-insight-block", () => ({
  MatchedInsightBlock: () => <div data-testid="matched-insight" />,
}));

function turn(overrides: Partial<ConversationTurn> = {}): ConversationTurn {
  return {
    id: 1,
    sequence: 1,
    created_at: "2026-08-31T05:31:45Z",
    updated_at: "2026-08-31T05:32:10Z",
    user_message: "Why is the backup job failure rate rising?",
    intent_type: null,
    status: "success",
    assistant_message: "The failure rate is increasing.",
    sql: null,
    result: null,
    chart_config: null,
    explanation: null,
    error_code: null,
    matched_insight: null,
    attachments: [],
    ...overrides,
  };
}

describe("AI Assistant dialogue timestamps", () => {
  it("renders stored user and AI timestamps hidden until message hover or focus", async () => {
    render(<TurnBubbles turn={turn()} />);

    const timestamps = await screen.findAllByTestId("message-timestamp");
    expect(timestamps).toHaveLength(2);

    for (const timestamp of timestamps) {
      expect(timestamp).toHaveClass("opacity-0");
      expect(timestamp).toHaveClass("group-hover:opacity-100");
      expect(timestamp).toHaveClass("group-focus-within:opacity-100");
    }

    expect(timestamps[0]).toHaveAccessibleName(/Sent .*2026/i);
    expect(timestamps[1]).toHaveAccessibleName(/Answered .*2026/i);
  });

  it("does not show an AI completion timestamp while the answer is pending", async () => {
    render(
      <TurnBubbles
        turn={turn({
          status: "pending",
          assistant_message: null,
        })}
      />,
    );

    const timestamps = await screen.findAllByTestId("message-timestamp");
    expect(timestamps).toHaveLength(1);
    expect(timestamps[0]).toHaveAccessibleName(/Sent .*2026/i);
  });

  it("omits timestamps safely when an older response has no timestamp fields", () => {
    render(
      <TurnBubbles
        turn={turn({
          created_at: undefined,
          updated_at: undefined,
        })}
      />,
    );

    expect(screen.queryByTestId("message-timestamp")).not.toBeInTheDocument();
  });
});
