import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

import { QuickActionsCard } from "./quick-actions-card";

function renderCard(canEdit = true) {
  return render(<QuickActionsCard projectId="7" canEdit={canEdit} />);
}

describe("QuickActionsCard", () => {
  beforeEach(() => push.mockReset());

  it("renders the five actions in order", () => {
    renderCard();
    const labels = screen
      .getAllByRole("listitem")
      .map((li) => li.textContent?.trim());
    expect(labels).toEqual([
      "Create datasource",
      "Create Database connection",
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

  it("routes Create datasource through the Data Source Builder", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Create datasource/ }));
    expect(push).toHaveBeenCalledWith("/data-source-builder?projectId=7");
  });

  it("routes Create Database connection through the Data Source Builder's database-only step", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Create Database connection/ }));
    expect(push).toHaveBeenCalledWith(
      "/data-source-builder?projectId=7&intent=database",
    );
  });

  it("routes Upload file through the Data Source Builder's upload-only step", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /Upload file/ }));
    expect(push).toHaveBeenCalledWith(
      "/data-source-builder?projectId=7&intent=upload",
    );
  });

  it("disables creation actions for viewers", () => {
    renderCard(false);
    expect(screen.getByRole("button", { name: /Create table/ })).toBeDisabled();
  });
});
