"use client";

import { useRef, useState } from "react";
import { IconFilePlus } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { Workspace, WorkspaceCard } from "@/lib/api/workspaces";
import { WorkspaceCanvas } from "./workspace-canvas";
import { isResourceDrag, readResourceDragData } from "./workspace-drag";
import type { AddableResource } from "./workspace-add-card";

/**
 * The Documents pane: the workspace's pinned resources, and the drop target
 * that fills it.
 *
 * The whole pane accepts a drop, not just the empty state or a narrow strip --
 * dragging a document out of the sidebar should land wherever it feels natural
 * to let go, including on top of the cards already there.
 */
export function WorkspaceFilesPane({
  workspace,
  editable,
  error,
  selectedCardId,
  onSelect,
  onAdd,
  onCardsChange,
}: {
  workspace: Workspace | null;
  editable: boolean;
  error: string | null;
  selectedCardId?: string | null;
  onSelect?: (card: WorkspaceCard) => void;
  onAdd: (resource: AddableResource) => void;
  onCardsChange: (cards: WorkspaceCard[]) => void;
}) {
  const [dragging, setDragging] = useState(false);
  // dragenter/dragleave fire for every child element the pointer crosses, so a
  // plain boolean flickers as the cursor moves over cards. Counting entries
  // against leaves tracks the pane as a whole.
  const depth = useRef(0);

  const canDrop = editable && workspace != null;

  const reset = () => {
    depth.current = 0;
    setDragging(false);
  };

  return (
    <div
      onDragEnter={(event) => {
        if (!canDrop || !isResourceDrag(event.dataTransfer)) return;
        event.preventDefault();
        depth.current += 1;
        setDragging(true);
      }}
      onDragOver={(event) => {
        if (!canDrop || !isResourceDrag(event.dataTransfer)) return;
        // Without preventDefault the browser refuses the drop entirely.
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={() => {
        if (!canDrop) return;
        depth.current -= 1;
        if (depth.current <= 0) reset();
      }}
      onDrop={(event) => {
        if (!canDrop) return;
        const resource = readResourceDragData(event.dataTransfer);
        reset();
        if (!resource) return;
        event.preventDefault();
        onAdd(resource);
      }}
      className={cn(
        "relative flex min-h-0 flex-1 flex-col overflow-y-auto",
        dragging && "bg-brand-50/40",
      )}
    >
      {error && (
        <p
          role="alert"
          className="m-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger"
        >
          {error}
        </p>
      )}

      <WorkspaceCanvas
        workspace={workspace}
        editable={editable}
        selectedCardId={selectedCardId}
        onSelect={onSelect}
        onCardsChange={onCardsChange}
      />

      {dragging && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-2 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-brand-500 bg-bg-primary/80 text-brand-700"
        >
          <IconFilePlus size={22} />
          <p className="text-[13px] font-medium">Drop to add to this workspace</p>
        </div>
      )}
    </div>
  );
}
