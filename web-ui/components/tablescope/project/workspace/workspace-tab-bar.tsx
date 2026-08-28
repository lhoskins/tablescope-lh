"use client";

import { useState } from "react";
import {
  IconDots,
  IconLock,
  IconPencil,
  IconPlus,
  IconShare,
  IconTrash,
  IconUsers,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { MenuItem } from "@/app/ai/menu-item";
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
  currentUserId = null,
  onRename,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  workspaces: Workspace[];
  activeWorkspaceId: number | null;
  onSelect: (workspaceId: number) => void;
  onCreate: () => void;
  creating?: boolean;
  currentUserId?: number | null;
  onRename?: (workspaceId: number, name: string) => void;
  onPublish?: (workspaceId: number) => void;
  onUnpublish?: (workspaceId: number) => void;
  onDelete?: (workspaceId: number) => void;
}) {
  return (
    <nav
      aria-label="Workspaces"
      className="flex items-center gap-1 overflow-x-auto border-b border-line-tertiary px-5 py-1.5"
    >
      {workspaces.map((workspace) => (
        <WorkspaceTabItem
          key={workspace.id}
          workspace={workspace}
          active={workspace.id === activeWorkspaceId}
          canManage={currentUserId != null && workspace.owner_user_id === currentUserId}
          onSelect={() => onSelect(workspace.id)}
          onRename={onRename ? (name) => onRename(workspace.id, name) : undefined}
          onPublish={onPublish ? () => onPublish(workspace.id) : undefined}
          onUnpublish={onUnpublish ? () => onUnpublish(workspace.id) : undefined}
          onDelete={onDelete ? () => onDelete(workspace.id) : undefined}
        />
      ))}
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

function WorkspaceTabItem({
  workspace,
  active,
  canManage,
  onSelect,
  onRename,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  workspace: Workspace;
  active: boolean;
  canManage: boolean;
  onSelect: () => void;
  onRename?: (name: string) => void;
  onPublish?: () => void;
  onUnpublish?: () => void;
  onDelete?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(workspace.name);

  const startRename = () => {
    setDraft(workspace.name);
    setEditing(true);
    setMenuOpen(false);
  };

  const commitRename = () => {
    const next = draft.trim();
    if (next && next !== workspace.name) onRename?.(next);
    setEditing(false);
  };

  const showMenu = canManage && (Boolean(onRename) || Boolean(onPublish) || Boolean(onUnpublish) || Boolean(onDelete));

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commitRename}
        onKeyDown={(e) => {
          if (e.key === "Enter") commitRename();
          if (e.key === "Escape") setEditing(false);
        }}
        className="min-w-0 max-w-[12rem] shrink-0 rounded-md border border-line-secondary bg-bg-primary px-2.5 py-1 text-[12px] font-medium text-ink-primary focus:border-brand-500 focus:outline-none"
      />
    );
  }

  return (
    <div className="group relative flex shrink-0 items-center">
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex items-center gap-1.5 rounded-md py-1 pl-2.5 text-[12px] font-medium transition-colors",
          showMenu ? "pr-6" : "pr-2.5",
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
      {showMenu && (
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label={`${workspace.name} actions`}
          className={cn(
            "absolute right-0.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-tertiary hover:text-ink-secondary",
            menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100",
          )}
        >
          <IconDots size={14} />
        </button>
      )}
      {menuOpen && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute right-0 top-8 z-50 w-40 overflow-hidden rounded-md border border-line-tertiary bg-bg-primary py-1 shadow-lg">
            {onRename && <MenuItem icon={<IconPencil size={14} />} label="Rename" onClick={startRename} />}
            {workspace.visibility === "shared_project"
              ? onUnpublish && (
                  <MenuItem
                    icon={<IconLock size={14} />}
                    label="Unpublish"
                    onClick={() => {
                      onUnpublish();
                      setMenuOpen(false);
                    }}
                  />
                )
              : onPublish && (
                  <MenuItem
                    icon={<IconShare size={14} />}
                    label="Publish"
                    onClick={() => {
                      onPublish();
                      setMenuOpen(false);
                    }}
                  />
                )}
            {onDelete && (
              <MenuItem
                icon={<IconTrash size={14} />}
                label="Delete"
                danger
                onClick={() => {
                  onDelete();
                  setMenuOpen(false);
                }}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
