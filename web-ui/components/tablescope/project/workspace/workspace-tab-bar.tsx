"use client";

import { IconPlus, IconUsers } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { Workspace } from "@/lib/api/workspaces";

/** The named-workspace strip shown only on the Workspace page. Distinct from
 *  `WorkspaceTabsBar`, which is the localStorage MRU strip of individual
 *  resources on every other project page. */
export function WorkspaceTabBar({
  workspaces,
  activeWorkspaceId,
  onSelect,
  onCreate,
  creating = false,
}: {
  workspaces: Workspace[];
  activeWorkspaceId: number | null;
  onSelect: (workspaceId: number) => void;
  onCreate: () => void;
  creating?: boolean;
}) {
  return (
    <nav
      aria-label="Workspaces"
      className="flex items-center gap-1 overflow-x-auto border-b border-line-tertiary px-5 py-1.5"
    >
      {workspaces.map((workspace) => {
        const active = workspace.id === activeWorkspaceId;
        return (
          <button
            key={workspace.id}
            type="button"
            onClick={() => onSelect(workspace.id)}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors",
              active
                ? "bg-brand-50 text-brand-700"
                : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
            )}
          >
            <span className="max-w-[12rem] truncate">{workspace.name}</span>
            {workspace.visibility === "shared_project" && (
              <IconUsers size={12} aria-label="Shared with the project" />
            )}
          </button>
        );
      })}
      <button
        type="button"
        onClick={onCreate}
        disabled={creating}
        aria-label="New workspace"
        title="New workspace"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary disabled:opacity-50"
      >
        <IconPlus size={13} />
      </button>
      <button
        type="button"
        onClick={onCreate}
        disabled={creating}
        className="shrink-0 rounded-md px-2.5 py-1 text-[12px] font-medium text-brand-600 hover:bg-brand-50 disabled:opacity-50"
      >
        + New Workspace
      </button>
    </nav>
  );
}
