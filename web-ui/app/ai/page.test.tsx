import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const {
  createConversation,
  listConversations,
  getConversation,
  replace,
  useSearchParamsMock,
} = vi.hoisted(() => ({
  createConversation: vi.fn(),
  listConversations: vi.fn().mockResolvedValue([]),
  getConversation: vi.fn(),
  replace: vi.fn(),
  useSearchParamsMock: vi.fn(() => new URLSearchParams()),
}));

function conversation(overrides: Record<string, unknown> = {}) {
  return {
    id: 99,
    project_id: null,
    surface: "ai_assistant",
    title: "New conversation",
    status: "active",
    active_datasource_id: null,
    canonical_key: null,
    merged_into_conversation_id: null,
    turns: [],
    updated_at: "2026-08-08T00:00:00Z",
    ...overrides,
  };
}

vi.mock("@/lib/api/conversational-analytics", () => ({
  createConversation: (payload: unknown) => createConversation(payload),
  listConversations: () => listConversations(),
  getConversation: (id: number) => getConversation(id),
  submitTurn: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => useSearchParamsMock(),
  usePathname: () => "/ai",
}));

vi.mock("@/lib/auth", () => ({
  getUserMeta: () => ({ userId: 1 }),
}));

vi.mock("@/lib/mfa", () => ({
  getMfaStatus: vi.fn().mockResolvedValue({
    roleRequiresMfa: false,
    tenantRequiresMfa: false,
    mfaSatisfied: true,
    hasVerifiedFactor: false,
  }),
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useCurrentUser: () => ({
    data: { user: { id: 1, rawRole: "admin" }, tenant: { id: 1, name: "Simplicit" } },
  }),
  useProjectSummaries: () => ({
    data: [
      { id: 1, name: "IT" },
      { id: 2, name: "Finance" },
    ],
  }),
}));

vi.mock("@/components/tablescope/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

import AiAssistantPage from "./page";

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AiAssistantPage />
    </QueryClientProvider>,
  );
}

describe("AiAssistantPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listConversations.mockResolvedValue([]);
    createConversation.mockResolvedValue(conversation({ project_id: 2 }));
    getConversation.mockResolvedValue(conversation({ project_id: 2 }));
    useSearchParamsMock.mockReturnValue(new URLSearchParams());
  });

  it("has no project picker at all — no select/combobox anywhere on the page", async () => {
    renderPage();

    await screen.findByLabelText("Message Tablescope AI");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Project$/)).not.toBeInTheDocument();
  });

  it("does not require a project to be picked before asking a question", async () => {
    renderPage();

    const input = await screen.findByLabelText("Message Tablescope AI");
    fireEvent.change(input, {
      target: { value: "Why is material cost increasing?" },
    });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(1));

    // The request must not force any project id — there is no UI to pick one
    // anymore. The backend (resolve_business_insight_project) resolves it
    // from the question text itself. Sending project_id: 0 (or any
    // placeholder) would make the backend 404 on "Project not found" instead
    // of routing.
    const payload = createConversation.mock.calls[0][0];
    expect(payload.project_id).toBeUndefined();
    expect(payload.initial_message).toBe("Why is material cost increasing?");

    // No blocking validation message should ever appear.
    expect(
      screen.queryByText(/please choose a project/i),
    ).not.toBeInTheDocument();
  });

  it("shows which project answered, read-only, once the conversation resolves one", async () => {
    renderPage();

    const input = await screen.findByLabelText("Message Tablescope AI");
    fireEvent.change(input, {
      target: { value: "Why is material cost increasing?" },
    });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(1));
    await screen.findByText("Finance");
    expect(screen.getByText(/answered from/i)).toBeInTheDocument();

    // Read-only — no interactive control backs it.
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("still honors a project supplied via a project-scoped deep link", async () => {
    // Deep links (e.g. "Ask AI" from a project page) are a different
    // mechanism than the removed manual picker — they should keep working.
    useSearchParamsMock.mockReturnValue(
      new URLSearchParams({ projectId: "2", q: "How is Finance doing?" }),
    );
    renderPage();

    await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(1));
    const payload = createConversation.mock.calls[0][0];
    expect(payload.project_id).toBe(2);
    expect(payload.initial_message).toBe("How is Finance doing?");
  });
});
