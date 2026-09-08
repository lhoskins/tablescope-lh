"use client";

import { IconCopy, IconMessage2, IconNote } from "@tabler/icons-react";
import type { CapturedSelection } from "./use-selection-capture";

/**
 * The floating action bar that appears over a text selection.
 *
 * Same interaction as the reference app's transcript capture -- highlight a
 * passage, act on it in place -- with Tablescope's extra target: a selection
 * can go to the Chat pane as pinned context as well as to Notes.
 *
 * Fixed-positioned against viewport coordinates and rendered above the panes,
 * so it isn't clipped by a pane's own overflow.
 */
export function SelectionToolbar({
  selection,
  onSendToChat,
  onSendToNotes,
  onCopy,
}: {
  selection: CapturedSelection;
  onSendToChat: () => void;
  onSendToNotes: () => void;
  onCopy: () => void;
}) {
  return (
    <div
      role="toolbar"
      aria-label="Use selected text"
      style={{
        top: Math.max(8, selection.top - 44),
        left: selection.left,
        transform: "translateX(-50%)",
      }}
      // pointerdown is stopped so clicking a button doesn't collapse the
      // selection before the handler reads it.
      onPointerDown={(event) => event.preventDefault()}
      className="fixed z-50 flex items-center gap-0.5 rounded-md bg-ink-primary px-1 py-1 shadow-lg"
    >
      <ToolbarButton label="Copy" onClick={onCopy}>
        <IconCopy size={13} />
        Copy
      </ToolbarButton>
      <ToolbarButton label="Send selection to Chat" onClick={onSendToChat}>
        <IconMessage2 size={13} />
        Chat
      </ToolbarButton>
      <ToolbarButton label="Send selection to Notes" onClick={onSendToNotes}>
        <IconNote size={13} />
        Notes
      </ToolbarButton>
    </div>
  );
}

function ToolbarButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex items-center gap-1 rounded px-2 py-1 text-[12px] font-medium text-white/90 hover:bg-white/15 hover:text-white"
    >
      {children}
    </button>
  );
}
