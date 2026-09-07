import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/44/actions",
  useSearchParams: () => new URLSearchParams(),
}));

import { RowMenu } from "./row-menu";
import type { ProjectActionListItem } from "@/lib/api/project-actions";

function item(overrides: Partial<ProjectActionListItem> = {}): ProjectActionListItem {
  return {
    id: 1,
    title: "Follow up with vendor",
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
    active_subtasks: 0,
    total_subtasks: 0,
    required_subtasks: 0,
    completed_required_subtasks: 0,
    comment_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    completed_at: null,
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    lock_version: 1,
    ...overrides,
  };
}

function openMenu() {
  fireEvent.click(screen.getByLabelText("Action menu"));
}

describe("RowMenu", () => {
  it("shows Archive (not Restore/Delete) for an active action", () => {
    const onArchive = vi.fn();
    render(
      <RowMenu
        projectId="44"
        item={item()}
        canManage
        onArchive={onArchive}
        onRestore={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    openMenu();
    expect(screen.getByText("Archive")).toBeInTheDocument();
    expect(screen.queryByText("Restore")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Archive"));
    expect(onArchive).toHaveBeenCalledTimes(1);
  });

  it("shows Restore and Delete (not Archive) for an archived action", () => {
    const onRestore = vi.fn();
    render(
      <RowMenu
        projectId="44"
        item={item({ archived_at: "2026-02-01T00:00:00Z" })}
        canManage
        onArchive={vi.fn()}
        onRestore={onRestore}
        onDelete={vi.fn()}
      />,
    );

    openMenu();
    expect(screen.getByText("Restore")).toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
    expect(screen.queryByText("Archive")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Restore"));
    expect(onRestore).toHaveBeenCalledTimes(1);
  });

  it("only calls onDelete after the confirmation dialog is accepted", () => {
    const onDelete = vi.fn();
    render(
      <RowMenu
        projectId="44"
        item={item({ archived_at: "2026-02-01T00:00:00Z", title: "Renew vendor contract" })}
        canManage
        onArchive={vi.fn()}
        onRestore={vi.fn()}
        onDelete={onDelete}
      />,
    );

    openMenu();
    fireEvent.click(screen.getByText("Delete"));

    // Menu click alone must not delete anything -- the confirm dialog gates it.
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByText("Delete this action?")).toBeInTheDocument();
    expect(screen.getByText(/Renew vendor contract/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("does not call onDelete when the confirmation dialog is cancelled", () => {
    const onDelete = vi.fn();
    render(
      <RowMenu
        projectId="44"
        item={item({ archived_at: "2026-02-01T00:00:00Z" })}
        canManage
        onArchive={vi.fn()}
        onRestore={vi.fn()}
        onDelete={onDelete}
      />,
    );

    openMenu();
    fireEvent.click(screen.getByText("Delete"));
    fireEvent.click(screen.getByText("Cancel"));

    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByText("Delete this action?")).not.toBeInTheDocument();
  });

  it("hides all lifecycle actions when the caller cannot manage actions", () => {
    render(
      <RowMenu
        projectId="44"
        item={item()}
        canManage={false}
        onArchive={vi.fn()}
        onRestore={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    openMenu();
    expect(screen.queryByText("Archive")).not.toBeInTheDocument();
    expect(screen.getByText("Open details")).toBeInTheDocument();
  });
});
