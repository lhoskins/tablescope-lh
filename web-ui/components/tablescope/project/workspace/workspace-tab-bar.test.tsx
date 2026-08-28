import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WorkspaceTabBar } from "./workspace-tab-bar";
import type { Workspace } from "@/lib/api/workspaces";

function workspace(overrides: Partial<Workspace> & { id: number; name: string }): Workspace {
  return {
    tenant_id: 1,
    project_id: 7,
    owner_user_id: 3,
    visibility: "private",
    published_at: null,
    created_at: "",
    updated_at: "",
    cards: [],
    ...overrides,
  };
}

describe("WorkspaceTabBar", () => {
  const workspaces = [
    workspace({ id: 1, name: "Revenue review" }),
    workspace({ id: 2, name: "Ops", visibility: "shared_project" }),
  ];

  it("marks the active named workspace and switches without navigating", () => {
    const onSelect = vi.fn();
    render(
      <WorkspaceTabBar
        workspaces={workspaces}
        activeWorkspaceId={1}
        onSelect={onSelect}
        onCreate={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /Revenue review/ }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("button", { name: /Ops/ }));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("creates a workspace from either add affordance", () => {
    const onCreate = vi.fn();
    render(
      <WorkspaceTabBar
        workspaces={workspaces}
        activeWorkspaceId={1}
        onSelect={vi.fn()}
        onCreate={onCreate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "New workspace" }));
    fireEvent.click(screen.getByRole("button", { name: "+ New Workspace" }));
    expect(onCreate).toHaveBeenCalledTimes(2);
  });
});
