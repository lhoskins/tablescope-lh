import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const updateProject = vi.fn();

vi.mock("@/lib/ui/use-shell-data", () => ({
  updateProject: (...args: unknown[]) => updateProject(...args),
}));

import { ProjectTitleBreadcrumb, ProjectTopBarControls } from "./project-topbar";
import type { ProjectSummary } from "@/lib/ui/types";

const project = {
  id: "7",
  name: "Sales",
  visibility: "shared",
  updatedLabel: "2 hours ago",
  documentCount: 0,
  queryCount: 0,
  dashboardCount: 0,
  aiStatus: "idle",
} as ProjectSummary;

function renderTitle(screenLabel?: string) {
  const client = new QueryClient();
  const onToast = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ProjectTitleBreadcrumb
        project={project}
        screenLabel={screenLabel}
        aiStatus="idle"
        onToast={onToast}
      />
    </QueryClientProvider>,
  );
  return { onToast };
}

describe("ProjectTitleBreadcrumb", () => {
  it("shows the project name and the current screen", () => {
    renderTitle("Documents");
    expect(screen.getByRole("button", { name: "Sales" })).toBeTruthy();
    expect(screen.getByText("Documents")).toBeTruthy();
  });

  it("renders the project name as clickable text with no separate edit icon", () => {
    renderTitle();
    const button = screen.getByRole("button", { name: "Sales" });
    expect(button).toBeTruthy();
    expect(button.querySelector("svg")).toBeNull();
  });

  it("clicking the name reveals an editable input with Save/Cancel", () => {
    renderTitle();
    fireEvent.click(screen.getByRole("button", { name: "Sales" }));
    expect(screen.getByLabelText("Project name")).toHaveValue("Sales");
    expect(screen.getByRole("button", { name: /save/i })).toBeTruthy();
  });

  it("saving a changed name calls updateProject", async () => {
    updateProject.mockResolvedValueOnce({});
    renderTitle();
    fireEvent.click(screen.getByRole("button", { name: "Sales" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Sales Ops" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("7", { name: "Sales Ops" }));
  });
});

describe("ProjectTopBarControls", () => {
  it("puts page actions before the sharing switch and Members", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ProjectTopBarControls
          project={project}
          actions={<button type="button">Add dashboard</button>}
          onMembers={vi.fn()}
          onToast={vi.fn()}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Add dashboard" })).toBeTruthy();
    expect(screen.getByRole("switch")).toBeTruthy();
    expect(screen.getByRole("button", { name: /members/i })).toBeTruthy();
  });
});
