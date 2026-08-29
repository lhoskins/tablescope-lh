import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { createConversation, listConversations, submitTurn } = vi.hoisted(() => ({
  createConversation: vi.fn(),
  listConversations: vi.fn().mockResolvedValue([
    { id: 1, project_id: 7, surface: "ai_assistant", title: "Prior chat", status: "active", canonical_key: null, merged_into_conversation_id: null, updated_at: "2026-08-08T00:00:00Z" },
  ]),
  submitTurn: vi.fn(),
}));

vi.mock("@/lib/api/conversational-analytics", () => ({
  createConversation: (payload: unknown) => createConversation(payload),
  listConversations: (projectId?: number) => listConversations(projectId),
  getConversation: vi.fn().mockResolvedValue({
    id: 1,
    project_id: 7,
    surface: "ai_assistant",
    title: "Prior chat",
    status: "active",
    active_datasource_id: null,
    canonical_key: null,
    merged_into_conversation_id: null,
    turns: [],
    updated_at: "2026-08-08T00:00:00Z",
  }),
  submitTurn: (id: number, data: unknown) => submitTurn(id, data),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
}));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

import { ProjectChatsScreen } from "./project-chats-screen";

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProjectChatsScreen projectId="7" />
    </QueryClientProvider>,
  );
}

describe("ProjectChatsScreen", () => {
  it("lists only this project's conversations", async () => {
    renderScreen();
    expect(listConversations).toHaveBeenCalledWith(7);
    await waitFor(() => expect(screen.getByText("Prior chat")).toBeTruthy());
  });

  it("scopes a new conversation to the current project", async () => {
    createConversation.mockResolvedValue({ id: 2, project_id: 7 });
    renderScreen();
    const input = await screen.findByLabelText("Ask about this project");
    fireEvent.change(input, { target: { value: "What tables do we have?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(createConversation).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: 7, initial_message: "What tables do we have?" }),
      ),
    );
  });
});
