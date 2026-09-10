import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-client";

const deleteProject = vi.fn();
const updateProject = vi.fn();

vi.mock("@/lib/ui/use-shell-data", () => ({
  deleteProject: (...args: unknown[]) => deleteProject(...args),
  updateProject: (...args: unknown[]) => updateProject(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { DeleteProjectButton, ProjectRowActions } from "./project-row-actions";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient();
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const project = { id: "7", name: "Sales" };

describe("DeleteProjectButton", () => {
  it("is visible on the project itself, not only in a list row", () => {
    renderWithClient(<DeleteProjectButton project={project} onToast={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Delete project" })).toBeTruthy();
  });

  it("requires typing the exact project name before confirming", () => {
    renderWithClient(<DeleteProjectButton project={project} onToast={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));

    const confirmButton = screen.getAllByRole("button", { name: "Delete project" })[1];
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Sales"), { target: { value: "wrong name" } });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Sales"), { target: { value: "Sales" } });
    expect(confirmButton).not.toBeDisabled();
  });

  it("deletes the project and calls onDeleted on success", async () => {
    deleteProject.mockResolvedValueOnce(undefined);
    const onToast = vi.fn();
    const onDeleted = vi.fn();
    renderWithClient(
      <DeleteProjectButton project={project} onToast={onToast} onDeleted={onDeleted} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    fireEvent.change(screen.getByPlaceholderText("Sales"), { target: { value: "Sales" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Delete project" })[1]);

    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith("7"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(onToast).toHaveBeenCalledWith("Project deleted.", "success");
  });

  it("shows a specific message and closes the dialog when a non-owner is blocked", async () => {
    deleteProject.mockRejectedValueOnce(new ApiError("Forbidden", 403));
    const onToast = vi.fn();
    renderWithClient(<DeleteProjectButton project={project} onToast={onToast} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    fireEvent.change(screen.getByPlaceholderText("Sales"), { target: { value: "Sales" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Delete project" })[1]);

    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(
        "Only the project owner or an admin can delete this project.",
        "error",
      ),
    );
    expect(screen.queryByText("Delete project?")).toBeNull();
  });
});

describe("ProjectRowActions", () => {
  it("still deletes a project from the list row's overflow menu", async () => {
    deleteProject.mockResolvedValueOnce(undefined);
    const onToast = vi.fn();
    renderWithClient(<ProjectRowActions project={project} onToast={onToast} />);

    fireEvent.click(screen.getByRole("button", { name: "Actions for Sales" }));
    await waitFor(() => expect(screen.getByText("Delete project")).toBeTruthy());
    fireEvent.click(screen.getByText("Delete project"));
    fireEvent.change(screen.getByPlaceholderText("Sales"), { target: { value: "Sales" } });
    fireEvent.click(screen.getByRole("button", { name: /^Delete project$/ }));

    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith("7"));
    expect(onToast).toHaveBeenCalledWith("Project deleted.", "success");
  });
});
