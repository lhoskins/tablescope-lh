import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn() }),
  usePathname: () => "/projects/44/actions/1",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({
    children,
    actions,
  }: {
    children?: React.ReactNode;
    actions?: React.ReactNode;
  }) => (
    <div data-testid="project-shell">
      <div data-testid="shell-actions">{actions}</div>
      {children}
    </div>
  ),
}));

vi.mock("@/lib/ui/use-project-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/ui/use-project-data")>();
  return { ...actual, useProjectMembers: () => ({ data: [] }) };
});

vi.mock("@/lib/ui/use-shell-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/ui/use-shell-data")>();
  return {
    ...actual,
    useCurrentUser: () => ({
      data: { user: { rawRole: "editor", isSuperAdmin: false } },
    }),
  };
});

vi.mock("@/components/ui/toast", () => ({
  useToasts: () => ({ push: vi.fn() }),
}));

const mockPush = vi.fn();

const { getAction, archive, restore, deletePermanently } = vi.hoisted(() => ({
  getAction: vi.fn(),
  archive: vi.fn().mockResolvedValue({ status: "archived", id: 1, lock_version: 2 }),
  restore: vi.fn().mockResolvedValue({}),
  deletePermanently: vi.fn().mockResolvedValue({ status: "deleted", id: 1, lock_version: 3 }),
}));

vi.mock("@/lib/api/project-actions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/project-actions")>();
  return {
    ...actual,
    projectActionsApi: {
      ...actual.projectActionsApi,
      get: getAction,
      archive,
      restore,
      deletePermanently,
    },
  };
});

import { ProjectActionDetail } from "./project-action-detail";
import type { ProjectAction } from "@/lib/api/project-actions";

function action(overrides: Partial<ProjectAction> = {}): ProjectAction {
  return {
    id: 1,
    title: "Renew vendor contract",
    description: null,
    status: "not_started",
    priority: "medium",
    owner_user_id: null,
    owner_name: null,
    due_date: null,
    percent_complete: 0,
    source_type: "manual",
    source_insight_id: null,
    source_insight_fingerprint: null,
    source_insight_type: null,
    source_insight_title: null,
    source_insight_snapshot: null,
    risk_impact: null,
    comment_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    completed_at: null,
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    lock_version: 1,
    subtasks: [],
    ...overrides,
  } as ProjectAction;
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProjectActionDetail projectId="44" actionId={1} />
    </QueryClientProvider>,
  );
}

describe("ProjectActionDetail lifecycle actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    archive.mockResolvedValue({ status: "archived", id: 1, lock_version: 2 });
    restore.mockResolvedValue({});
    deletePermanently.mockResolvedValue({ status: "deleted", id: 1, lock_version: 3 });
  });

  it("shows only Archive for an active action", async () => {
    getAction.mockResolvedValue(action());
    renderDetail();

    await waitFor(() => expect(screen.getByRole("button", { name: /Archive/i })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Restore/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/i })).not.toBeInTheDocument();
  });

  it("shows Restore and Delete (not Archive) for an archived action", async () => {
    getAction.mockResolvedValue(action({ archived_at: "2026-02-01T00:00:00Z" }));
    renderDetail();

    await waitFor(() => expect(screen.getByRole("button", { name: /Restore/i })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Delete/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Archive$/i })).not.toBeInTheDocument();
  });

  it("calls restore when Restore is clicked", async () => {
    getAction.mockResolvedValue(action({ archived_at: "2026-02-01T00:00:00Z" }));
    renderDetail();

    await waitFor(() => screen.getByRole("button", { name: /Restore/i }));
    fireEvent.click(screen.getByRole("button", { name: /Restore/i }));

    await waitFor(() => expect(restore).toHaveBeenCalledWith("44", 1));
  });

  it("requires confirmation before permanently deleting", async () => {
    getAction.mockResolvedValue(action({ archived_at: "2026-02-01T00:00:00Z" }));
    renderDetail();

    await waitFor(() => screen.getByRole("button", { name: /Delete/i }));
    fireEvent.click(screen.getByRole("button", { name: /Delete/i }));

    expect(deletePermanently).not.toHaveBeenCalled();
    expect(screen.getByText("Delete this action?")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" }).slice(-1)[0]);

    await waitFor(() => expect(deletePermanently).toHaveBeenCalledWith("44", 1));
    expect(mockPush).toHaveBeenCalledWith("/projects/44/actions");
  });
});
