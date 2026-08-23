import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const updateProject = vi.fn();

vi.mock("@/lib/ui/use-shell-data", () => ({
  updateProject: (...args: unknown[]) => updateProject(...args),
}));

import { ProjectHeader } from "./project-header";
import type { ProjectSummary } from "@/lib/ui/types";

function renderHeader(overrides: Partial<ProjectSummary> = {}) {
  const client = new QueryClient();
  const onToast = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ProjectHeader
        project={{ id: 7, name: "Sales", visibility: "shared", ...overrides } as ProjectSummary}
        memberCount={3}
        aiStatus="idle"
        onMembers={vi.fn()}
        onToast={onToast}
      />
    </QueryClientProvider>,
  );
  return { onToast };
}

describe("ProjectHeader", () => {
  it("renders the project name as clickable text with no separate edit icon", () => {
    renderHeader();
    const button = screen.getByRole("button", { name: "Sales" });
    expect(button).toBeTruthy();
    expect(button.querySelector("svg")).toBeNull();
  });

  it("clicking the name reveals an editable input with Save/Cancel", () => {
    renderHeader();
    fireEvent.click(screen.getByRole("button", { name: "Sales" }));
    expect(screen.getByLabelText("Project name")).toHaveValue("Sales");
    expect(screen.getByRole("button", { name: /save/i })).toBeTruthy();
  });

  it("saving a changed name calls updateProject", async () => {
    updateProject.mockResolvedValueOnce({});
    renderHeader();
    fireEvent.click(screen.getByRole("button", { name: "Sales" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Sales Ops" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("7", { name: "Sales Ops" }));
  });
});
