import type { AddableResource } from "./workspace-add-card";

/**
 * Dragging a resource from the sidebar into a workspace pane.
 *
 * Native HTML5 drag-and-drop rather than dnd-kit, which the panes use for
 * reordering: dnd-kit needs both ends inside one `DndContext`, and the sidebar
 * lives in the app shell while the panes live in the page. The browser's own
 * drag protocol crosses that boundary without hoisting state to a common
 * ancestor.
 *
 * A private MIME type is what makes the pane able to tell "a workspace
 * resource" from any other dragged thing (a file, selected text, a link) while
 * the pointer is still moving -- `getData` is blocked during `dragover`, but
 * `types` is readable, so the drop zone can light up only for payloads it can
 * actually accept.
 */
export const WORKSPACE_RESOURCE_MIME = "application/x-tablescope-resource";

export function setResourceDragData(
  dataTransfer: DataTransfer,
  resource: AddableResource,
): void {
  dataTransfer.setData(WORKSPACE_RESOURCE_MIME, JSON.stringify(resource));
  // A plain-text fallback so dragging somewhere else does something sane
  // rather than nothing.
  dataTransfer.setData("text/plain", resource.label);
  dataTransfer.effectAllowed = "copy";
}

/** True when the in-flight drag carries a resource this workspace can pin. */
export function isResourceDrag(dataTransfer: DataTransfer | null): boolean {
  return dataTransfer?.types?.includes(WORKSPACE_RESOURCE_MIME) ?? false;
}

export function readResourceDragData(
  dataTransfer: DataTransfer | null,
): AddableResource | null {
  const raw = dataTransfer?.getData(WORKSPACE_RESOURCE_MIME);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<AddableResource>;
    if (
      typeof parsed?.resource_type !== "string" ||
      typeof parsed?.resource_id !== "string"
    ) {
      return null;
    }
    return {
      resource_type: parsed.resource_type,
      resource_id: parsed.resource_id,
      label: typeof parsed.label === "string" ? parsed.label : parsed.resource_id,
    };
  } catch {
    // Another app's payload under the same type, or truncated JSON.
    return null;
  }
}
