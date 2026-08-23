import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

import { WorkspaceTabsBar } from "./workspace-tabs-bar";
import { saveWorkspaceTabs } from "./workspace-tabs-storage";

describe("WorkspaceTabsBar", () => {
  beforeEach(() => {
    window.localStorage.clear();
    push.mockClear();
  });

  it("renders nothing when there are no open tabs", () => {
    const { container } = render(
      <WorkspaceTabsBar projectId="7" activeItem={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("adds the active item as a tab and highlights it", () => {
    render(
      <WorkspaceTabsBar
        projectId="7"
        activeItem={{
          type: "table",
          id: "1",
          numericId: 1,
          label: "Monthly Revenue",
          href: "/projects/7/queries?q=1",
        }}
      />,
    );
    const tabButton = screen.getByRole("button", { name: "Monthly Revenue" });
    expect(tabButton).toBeTruthy();
    expect(tabButton).toHaveAttribute("aria-current", "page");
  });

  it("clicking a tab navigates to its href", () => {
    saveWorkspaceTabs("7", [
      { type: "dashboard", id: "2", label: "Sales Dashboard", href: "/projects/7/dashboards/2" },
    ]);
    render(<WorkspaceTabsBar projectId="7" activeItem={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Sales Dashboard" }));
    expect(push).toHaveBeenCalledWith("/projects/7/dashboards/2");
  });

  it("clicking the already-active tab does not navigate", () => {
    const activeItem = {
      type: "table" as const,
      id: "1",
      numericId: 1,
      label: "Monthly Revenue",
      href: "/projects/7/queries?q=1",
    };
    render(<WorkspaceTabsBar projectId="7" activeItem={activeItem} />);
    fireEvent.click(screen.getByRole("button", { name: "Monthly Revenue" }));
    // Re-pushing the same URL was re-triggering the underlying data view
    // (resetting pagination) even though nothing about the selection
    // changed -- clicking the tab you're already on must be a no-op.
    expect(push).not.toHaveBeenCalled();
  });

  it("switching to a different open tab does not reorder the strip", () => {
    saveWorkspaceTabs("7", [
      { type: "table", id: "1", label: "Left Tab", href: "/projects/7/queries?q=1" },
      { type: "table", id: "2", label: "Right Tab", href: "/projects/7/queries?q=2" },
    ]);
    render(
      <WorkspaceTabsBar
        projectId="7"
        activeItem={{ type: "table", id: "2", numericId: 2, label: "Right Tab", href: "/projects/7/queries?q=2" }}
      />,
    );
    const labels = screen.getAllByText(/^(Left Tab|Right Tab)$/).map((el) => el.textContent);
    expect(labels).toEqual(["Left Tab", "Right Tab"]);
  });

  it("closing the active tab navigates to the project overview when no tabs remain", () => {
    render(
      <WorkspaceTabsBar
        projectId="7"
        activeItem={{
          type: "document",
          id: "9",
          numericId: 9,
          label: "Q3 Deck",
          href: "/projects/7/documents/9",
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Close Q3 Deck" }));
    expect(push).toHaveBeenCalledWith("/projects/7");
  });
});
