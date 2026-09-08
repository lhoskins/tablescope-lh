import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useWorkspaceChat } from "./use-workspace-chat";
import type { WorkspaceCard } from "@/lib/api/workspaces";

const submitCanonicalTurn = vi.fn();
const listConversations = vi.fn();
const getConversation = vi.fn();

vi.mock("@/lib/api/conversational-analytics", () => ({
  submitCanonicalTurn: (...args: unknown[]) => submitCanonicalTurn(...args),
  listConversations: (...args: unknown[]) => listConversations(...args),
  getConversation: (...args: unknown[]) => getConversation(...args),
}));

function card(overrides: Partial<WorkspaceCard>): WorkspaceCard {
  return {
    id: 1,
    resource_type: "document",
    resource_id: "9001",
    view_mode: "card",
    position: 0,
    label: "Incident Report",
    ...overrides,
  } as WorkspaceCard;
}

const turn = { id: 1, sequence: 1, user_message: "hi", assistant_message: "ok" };

describe("useWorkspaceChat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    submitCanonicalTurn.mockResolvedValue({
      conversation_id: 7,
      conversation_created: true,
      surface: "project_workspace",
      project_id: 1,
      turn,
    });
    listConversations.mockResolvedValue([]);
  });

  function payload() {
    return submitCanonicalTurn.mock.calls[0][0];
  }

  it("grounds on every card and names the focused one", async () => {
    const cards = [card({}), card({ resource_type: "table", resource_id: "3001" })];
    const { result } = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards, focusedCard: cards[1], resume: false }),
    );

    await act(async () => void (await result.current.send("what changed?")));

    // The whole set travels, so the assistant can cross-reference...
    expect(payload().active_resources).toEqual([
      { resource_type: "document", resource_id: 9001 },
      { resource_type: "table", resource_id: 3001 },
    ]);
    // ...and the focus says which one the question is about.
    expect(payload().focused_resource).toEqual({
      resource_type: "table",
      resource_id: 3001,
    });
    expect(payload().surface).toBe("project_workspace");
    expect(payload().project_id).toBe(1);
  });

  it("coerces resource ids to numbers and drops ids that aren't numeric", async () => {
    // The backend resolves each id by primary key; a lifecycle-style string id
    // would fail validation and take the whole request with it.
    const cards = [card({}), card({ resource_type: "data_source", resource_id: "csv-abc" })];
    const { result } = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards, resume: false }),
    );

    await act(async () => void (await result.current.send("hello")));

    expect(payload().active_resources).toEqual([
      { resource_type: "document", resource_id: 9001 },
    ]);
  });

  it("omits the focus when the focused card has a non-numeric id", async () => {
    const focus = card({ resource_type: "data_source", resource_id: "csv-abc" });
    const { result } = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards: [card({})], focusedCard: focus, resume: false }),
    );

    await act(async () => void (await result.current.send("hello")));
    expect(payload().focused_resource).toBeUndefined();
  });

  it("resumes the project thread only when asked to", async () => {
    listConversations.mockResolvedValue([{ id: 7, surface: "project_workspace" }]);
    getConversation.mockResolvedValue({ id: 7, turns: [turn] });

    const drawer = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards: [], resume: false }),
    );
    await waitFor(() => expect(listConversations).not.toHaveBeenCalled());
    expect(drawer.result.current.turns).toEqual([]);

    const pane = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards: [], resume: true }),
    );
    await waitFor(() => expect(pane.result.current.turns).toEqual([turn]));
  });

  it("keeps quiet when there is no thread to resume", async () => {
    listConversations.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards: [], resume: true }),
    );
    await waitFor(() => expect(listConversations).toHaveBeenCalled());
    // A conversation the user may never have had is not an error worth showing.
    expect(result.current.error).toBeNull();
  });

  it("treats a cancelled request as a stop, not a failure", async () => {
    submitCanonicalTurn.mockRejectedValue(
      new DOMException("aborted", "AbortError"),
    );
    const { result } = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards: [card({})], resume: false }),
    );

    await act(async () => void (await result.current.send("hello")));

    expect(result.current.error).toBeNull();
    expect(result.current.busy).toBe(false);
  });

  it("surfaces a real failure", async () => {
    submitCanonicalTurn.mockRejectedValue(new Error("Rate limited"));
    const { result } = renderHook(() =>
      useWorkspaceChat({ projectId: "1", cards: [card({})], resume: false }),
    );

    await act(async () => void (await result.current.send("hello")));
    expect(result.current.error).toBe("Rate limited");
  });
});
