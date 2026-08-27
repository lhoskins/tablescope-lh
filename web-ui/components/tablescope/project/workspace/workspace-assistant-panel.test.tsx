import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const listConversations = vi.fn();
const getConversation = vi.fn();
const submitCanonicalTurn = vi.fn();

vi.mock("@/lib/api/conversational-analytics", () => ({
  listConversations: (...args: unknown[]) => listConversations(...args),
  getConversation: (...args: unknown[]) => getConversation(...args),
  submitCanonicalTurn: (...args: unknown[]) => submitCanonicalTurn(...args),
}));

vi.mock("@/components/tablescope/conversation/conversation-turn", () => ({
  TurnBubble: ({ turn }: { turn: { id: number; user_message: string } }) => (
    <div data-testid={`turn-${turn.id}`}>{turn.user_message}</div>
  ),
}));

import { WorkspaceAssistantPanel } from "./workspace-assistant-panel";

const ACTIVE_TABLE = {
  type: "table" as const,
  id: "1",
  numericId: 1,
  label: "Monthly Revenue",
  href: "/projects/7/queries?q=1",
};

describe("WorkspaceAssistantPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    listConversations.mockReset().mockResolvedValue([]);
    getConversation.mockReset();
    submitCanonicalTurn.mockReset();
  });

  it("shows an expand affordance when collapsed", () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "true");
    render(<WorkspaceAssistantPanel projectId="7" activeItem={null} />);
    expect(screen.getByLabelText("Open AI Assistant")).toBeTruthy();
    expect(screen.queryByLabelText("Ask the AI Assistant")).toBeNull();
  });

  it("defaults to collapsed and never fetches conversation history when nothing was persisted", () => {
    render(<WorkspaceAssistantPanel projectId="7" activeItem={null} />);
    expect(screen.getByLabelText("Open AI Assistant")).toBeTruthy();
    // The panel is present on every project page, so an unopened default
    // must not add a request to pages that never touch the assistant.
    expect(listConversations).not.toHaveBeenCalled();
  });

  it("resumes the existing project_workspace conversation once expanded", async () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "false");
    listConversations.mockResolvedValue([
      { id: 42, project_id: 7, surface: "project_workspace", title: "Workspace", status: "active", canonical_key: "project_workspace:7", merged_into_conversation_id: null, updated_at: "" },
    ]);
    getConversation.mockResolvedValue({
      id: 42,
      project_id: 7,
      surface: "project_workspace",
      title: "Workspace",
      status: "active",
      active_datasource_id: null,
      canonical_key: "project_workspace:7",
      merged_into_conversation_id: null,
      turns: [{ id: 1, user_message: "hello", sequence: 1 }],
      updated_at: "",
    });

    render(<WorkspaceAssistantPanel projectId="7" activeItem={null} />);

    await waitFor(() => expect(screen.getByTestId("turn-1")).toHaveTextContent("hello"));
  });

  it("sends a turn grounded on the active workspace tab", async () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "false");
    submitCanonicalTurn.mockResolvedValue({
      conversation_id: 42,
      conversation_created: true,
      surface: "project_workspace",
      project_id: 7,
      turn: { id: 1, user_message: "What changed?", sequence: 1 },
    });

    render(<WorkspaceAssistantPanel projectId="7" activeItem={ACTIVE_TABLE} />);

    fireEvent.change(screen.getByLabelText("Ask the AI Assistant"), {
      target: { value: "What changed?" },
    });
    fireEvent.keyDown(screen.getByLabelText("Ask the AI Assistant"), { key: "Enter" });

    await waitFor(() =>
      expect(submitCanonicalTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          surface: "project_workspace",
          project_id: 7,
          message: "What changed?",
          active_resource_type: "table",
          active_resource_id: 1,
        }),
        expect.any(AbortSignal),
      ),
    );
    await waitFor(() => expect(screen.getByTestId("turn-1")).toHaveTextContent("What changed?"));
  });

  it("uses the canonical project_insights conversation for Project Insights", async () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "false");
    submitCanonicalTurn.mockResolvedValue({
      conversation_id: 44,
      conversation_created: true,
      surface: "project_insights",
      project_id: 7,
      turn: { id: 3, user_message: "What is the top risk?", sequence: 1 },
    });

    render(
      <WorkspaceAssistantPanel
        projectId="7"
        activeItem={null}
        surface="project_insights"
        contextLabel="Project Insights"
      />,
    );

    fireEvent.change(screen.getByLabelText("Ask the AI Assistant"), {
      target: { value: "What is the top risk?" },
    });
    fireEvent.keyDown(screen.getByLabelText("Ask the AI Assistant"), {
      key: "Enter",
    });

    await waitFor(() =>
      expect(submitCanonicalTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          surface: "project_insights",
          project_id: 7,
          message: "What is the top risk?",
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("supports the global Home assistant without a project id", async () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "false");
    submitCanonicalTurn.mockResolvedValue({
      conversation_id: 43,
      conversation_created: true,
      surface: "business_insights",
      project_id: null,
      turn: { id: 2, user_message: "What needs attention?", sequence: 1 },
    });

    render(
      <WorkspaceAssistantPanel
        surface="business_insights"
        contextLabel="Personal Home"
      />,
    );
    fireEvent.change(screen.getByLabelText("Ask the AI Assistant"), {
      target: { value: "What needs attention?" },
    });
    fireEvent.keyDown(screen.getByLabelText("Ask the AI Assistant"), { key: "Enter" });

    await waitFor(() =>
      expect(submitCanonicalTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          surface: "business_insights",
          project_id: undefined,
          message: "What needs attention?",
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("exposes voice input and a stop button while a turn is in flight", async () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "false");
    submitCanonicalTurn.mockImplementation(() => new Promise(() => {}));

    render(<WorkspaceAssistantPanel projectId="7" activeItem={null} />);

    expect(screen.getByLabelText("Speak your question")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Ask the AI Assistant"), {
      target: { value: "What changed?" },
    });
    fireEvent.keyDown(screen.getByLabelText("Ask the AI Assistant"), { key: "Enter" });

    const stopButton = await screen.findByLabelText("Stop");
    const [, signal] = submitCanonicalTurn.mock.calls[0] as [unknown, AbortSignal];
    expect(signal.aborted).toBe(false);
    fireEvent.click(stopButton);
    expect(signal.aborted).toBe(true);
  });

  it("collapsing the panel persists the collapsed state", () => {
    window.localStorage.setItem("tablescope:workspace-assistant-collapsed", "false");
    render(<WorkspaceAssistantPanel projectId="7" activeItem={null} />);
    fireEvent.click(screen.getByLabelText("Collapse AI Assistant panel"));
    expect(window.localStorage.getItem("tablescope:workspace-assistant-collapsed")).toBe("true");
  });
});
