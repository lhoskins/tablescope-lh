import { describe, expect, it } from "vitest";
import { groupConversationSummaries } from "./group-canonical";
import type { ConversationSummary } from "@/lib/api/conversational-analytics";

function makeConversation(
  overrides: Partial<ConversationSummary> = {},
): ConversationSummary {
  return {
    id: 1,
    project_id: null,
    surface: "ai_assistant",
    title: "Chat",
    status: "active",
    canonical_key: null,
    merged_into_conversation_id: null,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("groupConversationSummaries", () => {
  it("groups canonical business insights into a single row", () => {
    const conversations = [
      makeConversation({ id: 1, canonical_key: "business_insights", updated_at: "2026-01-01T00:00:00Z" }),
      makeConversation({ id: 2, canonical_key: "business_insights", updated_at: "2026-01-02T00:00:00Z" }),
    ];
    const result = groupConversationSummaries(conversations, []);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Business Insights");
    expect(result[0].id).toBe(2);
  });

  it("groups canonical project insights per project and uses the project name", () => {
    const conversations = [
      makeConversation({
        id: 3,
        project_id: 10,
        canonical_key: "project_insights:10",
        updated_at: "2026-01-01T00:00:00Z",
      }),
      makeConversation({
        id: 4,
        project_id: 10,
        canonical_key: "project_insights:10",
        updated_at: "2026-01-03T00:00:00Z",
      }),
      makeConversation({
        id: 5,
        project_id: 20,
        canonical_key: "project_insights:20",
        updated_at: "2026-01-02T00:00:00Z",
      }),
    ];
    const result = groupConversationSummaries(conversations, [
      { id: 10, name: "Alpha" },
      { id: 20, name: "Beta" },
    ] as any);
    expect(result).toHaveLength(2);
    expect(result.find((r) => r.id === 4)?.title).toBe("Project Insights — Alpha");
    expect(result.find((r) => r.id === 5)?.title).toBe("Project Insights — Beta");
  });

  it("keeps manual chats as individual rows", () => {
    const conversations = [
      makeConversation({ id: 6, canonical_key: null, title: "Manual one" }),
      makeConversation({ id: 7, canonical_key: null, title: "Manual two" }),
    ];
    const result = groupConversationSummaries(conversations, []);
    expect(result).toHaveLength(2);
    expect(result.map((r) => r.title)).toEqual(["Manual one", "Manual two"]);
  });
});
