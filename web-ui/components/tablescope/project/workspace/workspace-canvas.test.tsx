import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WorkspaceCanvas, toCardPatch } from "./workspace-canvas";
import type { Workspace, WorkspaceCard } from "@/lib/api/workspaces";

const CARDS: WorkspaceCard[] = [
  { id: 1, resource_type: "table", resource_id: "1", view_mode: "card", position: 0, label: "Monthly Revenue" },
  { id: 2, resource_type: "dashboard", resource_id: "5", view_mode: "row", position: 1, label: "Exec Overview" },
];

const WORKSPACE: Workspace = {
  id: 9,
  tenant_id: 1,
  project_id: 7,
  owner_user_id: 3,
  name: "Revenue review",
  visibility: "private",
  published_at: null,
  created_at: "",
  updated_at: "",
  cards: CARDS,
};

describe("WorkspaceCanvas", () => {
  it("renders each card in its persisted view mode", () => {
    render(<WorkspaceCanvas workspace={WORKSPACE} editable onCardsChange={vi.fn()} />);
    expect(screen.getByLabelText("Monthly Revenue").getAttribute("data-view-mode")).toBe("card");
    expect(screen.getByLabelText("Exec Overview").getAttribute("data-view-mode")).toBe("row");
  });

  it("changes a card's view mode", () => {
    const onCardsChange = vi.fn();
    render(<WorkspaceCanvas workspace={WORKSPACE} editable onCardsChange={onCardsChange} />);
    const group = screen.getByRole("group", { name: "View mode for Monthly Revenue" });
    fireEvent.click(within(group, "Full"));
    expect(onCardsChange.mock.calls[0][0][0].view_mode).toBe("full");
  });

  it("removes and reorders cards", () => {
    const onCardsChange = vi.fn();
    render(<WorkspaceCanvas workspace={WORKSPACE} editable onCardsChange={onCardsChange} />);

    fireEvent.click(screen.getByLabelText("Remove Monthly Revenue"));
    expect(onCardsChange.mock.calls[0][0].map((c: WorkspaceCard) => c.id)).toEqual([2]);

    fireEvent.click(screen.getByLabelText("Move Exec Overview earlier"));
    expect(onCardsChange.mock.calls[1][0].map((c: WorkspaceCard) => c.id)).toEqual([2, 1]);
  });

  it("hides card edit controls for non-owners", () => {
    render(<WorkspaceCanvas workspace={WORKSPACE} editable={false} onCardsChange={vi.fn()} />);
    expect(screen.queryByLabelText("Remove Monthly Revenue")).toBeNull();
  });

  it("renumbers positions for the full-array PATCH body", () => {
    expect(toCardPatch([CARDS[1], CARDS[0]])).toEqual([
      { resource_type: "dashboard", resource_id: "5", view_mode: "row", position: 0 },
      { resource_type: "table", resource_id: "1", view_mode: "card", position: 1 },
    ]);
  });
});

function within(container: HTMLElement, label: string): HTMLElement {
  const match = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent === label,
  );
  if (!match) throw new Error(`No button labelled ${label}`);
  return match;
}
