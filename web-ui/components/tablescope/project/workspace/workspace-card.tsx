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

const VIEW_MODES: { mode: WorkspaceCardViewMode; label: string }[] = [
  { mode: "card", label: "Card" },
  { mode: "row", label: "Row" },
  { mode: "full", label: "Full" },
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

  return (
    <article
      aria-label={title}
      data-view-mode={card.view_mode}
      className={cn(
        "flex flex-col rounded-lg border border-line-tertiary bg-bg-primary",
        card.view_mode === "card" && "col-span-1 min-h-[180px]",
        card.view_mode === "row" && "col-span-full min-h-[120px]",
        card.view_mode === "full" && "col-span-full min-h-[420px]",
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b border-line-tertiary px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <Icon size={14} className="shrink-0 text-ink-tertiary" />
          <h3 className="truncate text-[13px] font-medium text-ink-primary">{title}</h3>
        </div>
        {editable && (
          <div className="flex items-center gap-1">
            <div role="group" aria-label={`View mode for ${title}`} className="flex items-center gap-0.5">
              {VIEW_MODES.map(({ mode, label }) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => onViewModeChange(mode)}
                  aria-pressed={card.view_mode === mode}
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors",
                    card.view_mode === mode
                      ? "bg-brand-50 text-brand-700"
                      : "text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => onMove(-1)}
              aria-label={`Move ${title} earlier`}
              className="rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              <IconChevronLeft size={13} />
            </button>
            <button
              type="button"
              onClick={() => onMove(1)}
              aria-label={`Move ${title} later`}
              className="rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              <IconChevronRight size={13} />
            </button>
            <button
              type="button"
              onClick={onRemove}
              aria-label={`Remove ${title}`}
              className="rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              <IconX size={13} />
            </button>
          </div>
        )}
      </header>
      <div className="flex-1 px-3 py-2 text-[12px] text-ink-tertiary">
        {card.label
          ? `${card.resource_type.replace("_", " ")} preview`
          : "This resource is no longer available in the project."}
      </div>
    </article>
  );
}
