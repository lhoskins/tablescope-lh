import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WorkspaceFilesPane } from "./workspace-files-pane";
import { WORKSPACE_RESOURCE_MIME } from "./workspace-drag";
import type { Workspace } from "@/lib/api/workspaces";

const WORKSPACE: Workspace = {
  id: 1,
  tenant_id: 1,
  project_id: 1,
  owner_user_id: 1,
  name: "Cost review",
  visibility: "private",
  published_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  cards: [],
};

/** jsdom has no DataTransfer, so stand in with the bits the pane reads. */
function dragPayload(data: Record<string, string>) {
  return {
    types: Object.keys(data),
    getData: (type: string) => data[type] ?? "",
    setData: vi.fn(),
    dropEffect: "none",
    effectAllowed: "all",
  } as unknown as DataTransfer;
}

const DOCUMENT_DRAG = dragPayload({
  [WORKSPACE_RESOURCE_MIME]: JSON.stringify({
    resource_type: "document",
    resource_id: "9001",
    label: "Incident Report",
  }),
});

function renderPane(overrides: Partial<Parameters<typeof WorkspaceFilesPane>[0]> = {}) {
  const onAdd = vi.fn();
  const { container } = render(
    <WorkspaceFilesPane
      workspace={WORKSPACE}
      editable
      error={null}
      onAdd={onAdd}
      onCardsChange={vi.fn()}
      {...overrides}
    />,
  );
  // The drop target is the pane's own root element.
  return { onAdd, zone: container.firstChild as HTMLElement };
}

describe("WorkspaceFilesPane", () => {
  it("pins a resource dragged in from the sidebar", () => {
    const { onAdd, zone } = renderPane();

    fireEvent.dragEnter(zone, { dataTransfer: DOCUMENT_DRAG });
    expect(screen.getByText("Drop to add to this workspace")).toBeTruthy();

    fireEvent.drop(zone, { dataTransfer: DOCUMENT_DRAG });
    expect(onAdd).toHaveBeenCalledWith({
      resource_type: "document",
      resource_id: "9001",
      label: "Incident Report",
    });
    // The prompt clears once the drag is over.
    expect(screen.queryByText("Drop to add to this workspace")).toBeNull();
  });

  it("ignores drags that aren't workspace resources", () => {
    const { onAdd, zone } = renderPane();
    const fileDrag = dragPayload({ "text/plain": "just some text" });

    fireEvent.dragEnter(zone, { dataTransfer: fileDrag });
    // No prompt: the pane only lights up for payloads it can accept.
    expect(screen.queryByText("Drop to add to this workspace")).toBeNull();

    fireEvent.drop(zone, { dataTransfer: fileDrag });
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("refuses drops for viewers who cannot edit the workspace", () => {
    const { onAdd, zone } = renderPane({ editable: false });

    fireEvent.dragEnter(zone, { dataTransfer: DOCUMENT_DRAG });
    expect(screen.queryByText("Drop to add to this workspace")).toBeNull();

    fireEvent.drop(zone, { dataTransfer: DOCUMENT_DRAG });
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("keeps the prompt up while the pointer crosses child elements", () => {
    const { zone } = renderPane();

    // dragenter/dragleave fire per child; the pane tracks depth so the prompt
    // doesn't flicker as the cursor moves across cards inside it.
    fireEvent.dragEnter(zone, { dataTransfer: DOCUMENT_DRAG });
    fireEvent.dragEnter(zone, { dataTransfer: DOCUMENT_DRAG });
    fireEvent.dragLeave(zone);
    expect(screen.getByText("Drop to add to this workspace")).toBeTruthy();

    fireEvent.dragLeave(zone);
    expect(screen.queryByText("Drop to add to this workspace")).toBeNull();
  });
});
