import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProjectActionsWorkspace } from "./project-actions-workspace";
import { useProjectActionsBoard } from "./hooks/use-project-actions-board";

// Regression test for: after a project's only action is archived, the
// "New action" button in the toolbar appeared to do nothing. The board's
// zero-non-archived-items empty state and the group-based inline "add
// action" row are mutually exclusive branches -- clicking "New action" only
// updates state consumed by the group board, which never mounted while the
// empty state was showing.

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({ children }: { children?: ReactNode }) => (
    <div data-testid="project-shell">{children}</div>
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
      data: {
        user: { id: 1, rawRole: "editor", isSuperAdmin: false },
        tenant: { slug: "acme" },
      },
    }),
  };
});

vi.mock("@/components/ui/toast", () => ({
  useToasts: () => ({ push: vi.fn() }),
}));

vi.mock("./hooks/use-project-actions-board", () => ({
  useProjectActionsBoard: vi.fn(),
}));

function mutation() {
  return { mutate: vi.fn() };
}

function boardHookReturn() {
  return {
    prefs: {
      view: "board" as const,
      groupBy: "status" as const,
      sortBy: "updated" as const,
      sortDirection: "desc" as const,
      visibleColumns: [],
      collapsedGroups: [],
    },
    savePrefs: vi.fn(),
    search: "",
    setSearch: vi.fn(),
    filters: {},
    setFilters: vi.fn(),
    boardQuery: {
      isLoading: false,
      data: {
        items: [],
        total: 0,
        summary: { active: 0, overdue: 0, avg_progress: 0, risk_mitigations_completed: 0, groups: [] },
      },
    },
    fetchDetail: vi.fn(),
    updateAction: mutation(),
    archiveAction: mutation(),
    restoreAction: mutation(),
    deleteAction: mutation(),
    reviewAction: mutation(),
    createSubtask: mutation(),
    updateSubtask: mutation(),
    archiveSubtask: mutation(),
    bulkUpdate: mutation(),
    createAction: mutation(),
    currentUserId: 1,
  };
}

describe("ProjectActionsWorkspace", () => {
  it("shows the inline add-action row when 'New action' is clicked with zero non-archived actions", () => {
    vi.mocked(useProjectActionsBoard).mockReturnValue(
      boardHookReturn() as unknown as ReturnType<typeof useProjectActionsBoard>,
    );

    render(<ProjectActionsWorkspace projectId="44" />);

    // The empty state is showing (this is the state right after archiving
    // a project's only action).
    expect(screen.getByText("No actions match the current filters.")).toBeInTheDocument();

    const newActionButton = screen.getByRole("button", { name: /new action/i });
    expect(newActionButton).toBeEnabled();
    fireEvent.click(newActionButton);

    // The empty state must be replaced by the inline add-action row, not
    // silently swallowed.
    expect(screen.queryByText("No actions match the current filters.")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("New action")).toBeInTheDocument();
  });
});
