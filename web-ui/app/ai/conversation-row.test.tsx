import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  ConversationRow,
  formatConversationTimestamp,
} from "./conversation-row";
import type { ConversationSummary } from "@/lib/api/conversational-analytics";

const conversation: ConversationSummary = {
  id: 42,
  project_id: null,
  surface: "ai_assistant",
  title: "Quarterly revenue analysis",
  status: "active",
  canonical_key: null,
  merged_into_conversation_id: null,
  updated_at: "2026-08-31T19:42:18Z",
};

function renderRow(active = false) {
  return render(
    <ConversationRow
      conversation={conversation}
      active={active}
      onSelect={vi.fn()}
      onRename={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
}

describe("ConversationRow timestamp", () => {
  it("shows the localized conversation date and time when the conversation is active", async () => {
    renderRow(true);

    const timestamp = await screen.findByTestId("conversation-timestamp");
    const expected = formatConversationTimestamp(conversation.updated_at);
    expect(expected).not.toBeNull();
    expect(timestamp).toHaveTextContent(expected!.compact);
    expect(timestamp).toHaveClass("opacity-100");
  });

  it("keeps the timestamp rendered for hover and keyboard focus", async () => {
    renderRow(false);

    const timestamp = await screen.findByTestId("conversation-timestamp");
    expect(timestamp).toHaveClass("opacity-0");
    expect(timestamp).toHaveClass("group-hover:opacity-100");
    expect(timestamp).toHaveClass("group-focus-within:opacity-100");
  });

  it("provides the full localized timestamp in the conversation tooltip and accessible label", async () => {
    renderRow();

    const button = await screen.findByRole("button", {
      name: /Quarterly revenue analysis, last updated/i,
    });
    expect(button).toHaveAttribute("title", expect.stringContaining("Last updated"));
    expect(button.getAttribute("title")).toContain("2026");
  });

  it("does not render a misleading timestamp for an invalid API value", () => {
    expect(formatConversationTimestamp("not-a-date")).toBeNull();
  });
});
