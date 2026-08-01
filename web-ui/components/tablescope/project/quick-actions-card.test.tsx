import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@/components/datasource/ConnectorsMenu", () => ({
  ConnectorsMenu: ({ label }: { label: string }) => <button>{label}</button>,
}));

vi.mock("@/components/uploads/unified-upload-dialog", () => ({
  UnifiedUploadDialog: ({ open }: { open: boolean }) =>
    open ? <div>AI-Assisted Upload</div> : null,
}));

import { QuickActionsCard } from "./quick-actions-card";

function renderCard(canEdit = true) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <QuickActionsCard projectId="7" canEdit={canEdit} onSourceCreated={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("QuickActionsCard", () => {
  beforeEach(() => push.mockReset());

  it("renders the four actions in order", () => {
    renderCard();
    const labels = screen
      .getAllByRole("listitem")
      .map((li) => li.textContent?.trim());
    expect(labels).toEqual([
      "Add data source",
      "Create table",
      "Upload file",
      "New dashboard",
    ]);
  });

  it("stacks the actions in a single column", () => {
    renderCard();
    const list = screen.getByTestId("quick-actions-list");
    expect(list.className).toContain("flex-col");
    expect(list.className).not.toContain("grid-cols-2");
  });

  it("routes each action to its project workflow", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Create table/ }));
    expect(push).toHaveBeenCalledWith("/projects/7/queries");

    fireEvent.click(screen.getByRole("button", { name: /New dashboard/ }));
    expect(push).toHaveBeenCalledWith("/projects/7/dashboards");
  });

  it("opens the unified upload intake instead of navigating to Documents", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Upload file/ }));
    expect(screen.getByText("AI-Assisted Upload")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("disables creation actions for viewers", () => {
    renderCard(false);
    expect(screen.getByRole("button", { name: /Create table/ })).toBeDisabled();
  });
});
