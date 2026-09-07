"use client";

import {
  IconChevronLeft,
  IconChevronRight,
  IconDatabase,
  IconFileText,
  IconLayoutDashboard,
  IconTable,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { WorkspaceCard as WorkspaceCardModel, WorkspaceCardViewMode } from "@/lib/api/workspaces";
import type { WorkspaceResourceType } from "./workspace-tabs-storage";

const TYPE_ICON: Record<WorkspaceResourceType, typeof IconTable> = {
  table: IconTable,
  dashboard: IconLayoutDashboard,
  document: IconFileText,
  data_source: IconDatabase,
};

// Card mode abbreviates to single letters, because a card sized to a narrow
// pane can't fit "Card Row Full" plus the move and remove controls without
// them hanging off the edge. Row and full span the pane, so they have room for
// the words. Either way the full name is the accessible name.
const VIEW_MODES: { mode: WorkspaceCardViewMode; label: string; short: string }[] = [
  { mode: "card", label: "Card", short: "C" },
  { mode: "row", label: "Row", short: "R" },
  { mode: "full", label: "Full", short: "F" },
];

export function WorkspaceCard({
  card,
  editable,
  onViewModeChange,
  onRemove,
  onMove,
}: {
  card: WorkspaceCardModel;
  /** Card edits are owner-only, matching publish/unpublish. */
  editable: boolean;
  onViewModeChange: (mode: WorkspaceCardViewMode) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const Icon = TYPE_ICON[card.resource_type] ?? IconTable;
  const title = card.label ?? `${card.resource_type} ${card.resource_id}`;
  const compact = card.view_mode === "card";

  return (
    <article
      aria-label={title}
      data-view-mode={card.view_mode}
      className={cn(
        // The floor width keeps the header's controls inside the card even in
        // the narrowest pane; below this the row would spill past the border.
        "flex min-w-[184px] flex-col rounded-lg border border-line-tertiary bg-bg-primary",
        card.view_mode === "card" && "col-span-1 min-h-[180px]",
        card.view_mode === "row" && "col-span-full min-h-[120px]",
        card.view_mode === "full" && "col-span-full min-h-[420px]",
      )}
    >
      {/* Controls only. The title sits in the card body below, where it has the
          full width to wrap -- sharing this row with six controls truncated it
          to a few useless characters ("It 003 …"). */}
      <header className="flex items-center justify-end gap-1 border-b border-line-tertiary px-2 py-1.5">
        {editable && (
          <div className="flex shrink-0 items-center">
            <div role="group" aria-label={`View mode for ${title}`} className="flex items-center">
              {VIEW_MODES.map(({ mode, label, short }) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => onViewModeChange(mode)}
                  title={label}
                  aria-label={label}
                  aria-pressed={card.view_mode === mode}
                  className={cn(
                    "h-5 rounded text-[11px] font-semibold leading-none transition-colors",
                    compact ? "w-5" : "px-1.5",
                    card.view_mode === mode
                      ? "bg-brand-50 text-brand-700"
                      : "text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary",
                  )}
                >
                  {compact ? short : label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => onMove(-1)}
              title="Move earlier"
              aria-label={`Move ${title} earlier`}
              className="flex h-5 w-5 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              <IconChevronLeft size={13} />
            </button>
            <button
              type="button"
              onClick={() => onMove(1)}
              title="Move later"
              aria-label={`Move ${title} later`}
              className="flex h-5 w-5 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              <IconChevronRight size={13} />
            </button>
            <button
              type="button"
              onClick={onRemove}
              title="Remove from workspace"
              aria-label={`Remove ${title}`}
              className="flex h-5 w-5 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-danger"
            >
              <IconX size={13} />
            </button>
          </div>
        )}
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-1 px-3 py-2">
        <div className="flex items-start gap-1.5">
          <Icon size={14} className="mt-px shrink-0 text-ink-tertiary" />
          <h3 className="break-words text-[13px] font-medium leading-snug text-ink-primary">
            {title}
          </h3>
        </div>
        <p className="text-[12px] text-ink-tertiary">
          {card.label
            ? `${card.resource_type.replace("_", " ")} preview`
            : "This resource is no longer available in the project."}
        </p>
      </div>
    </article>
  );
}
