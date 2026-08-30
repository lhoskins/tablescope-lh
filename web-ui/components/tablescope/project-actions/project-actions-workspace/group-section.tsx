"use client";


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { initials, timeAgo } from "@/lib/ui/format";
import { useProjectActionsBoard } from "../hooks/use-project-actions-board";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { useToasts } from "@/components/ui/toast";
import {
  type ProjectActionListItem,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
  type ProjectActionGroupBy,
  type ProjectActionSortBy,
  type ProjectActionView,
  type ProjectAction,
  type ProjectActionFilters,
} from "@/lib/api/project-actions";
import {
  IconPlus,
  IconSearch,
  IconChevronDown,
  IconChevronRight,
  IconMessage,
  IconDotsVertical,
  IconLoader2,
  IconClipboardList,
  IconClock,
  IconTrendingUp,
  IconShieldCheck,
  IconSparkles,
  IconCalendar,
  IconTrash,
} from "@tabler/icons-react";import { groupTone } from "./group-tone";
import { groupTextClass } from "./group-text-class";
import { ColumnHeader } from "./column-header";
import { ActionRow } from "./action-row";



export function GroupSection({
  projectId,
  group,
  expanded,
  onToggle,
  gridTemplate,
  selected,
  onSelect,
  onExpand,
  expandedRows,
  detailMap,
  canManage,
  onStatusChange,
  onPriorityChange,
  onOwnerChange,
  onDueChange,
  onArchive,
  onRestore,
  onSubtaskStatusChange,
  onSubtaskFieldChange,
  onSubtaskArchive,
  onAddSubtask,
  members,
  adding,
  newActionTitle,
  setNewActionTitle,
  onAddAction,
  onSubmitNewAction,
  onCancelAdd,
}: {
  projectId: string;
  group: { group: string; label: string; count: number; overdue_count: number; avg_progress: number; items: ProjectActionListItem[] };
  expanded: boolean;
  onToggle: () => void;
  gridTemplate: string;
  selected: Set<number>;
  onSelect: (id: number) => void;
  onExpand: (id: number) => void;
  expandedRows: Set<number>;
  detailMap: Record<number, ProjectAction>;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner_user_id: number | null, version: number) => void;
  onDueChange: (id: number, due_date: string | null, version: number) => void;
  onArchive: (id: number, version: number) => void;
  onRestore: (id: number) => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  adding: boolean;
  newActionTitle: string;
  setNewActionTitle: (v: string) => void;
  onAddAction: () => void;
  onSubmitNewAction: (group: string, title: string) => void;
  onCancelAdd: () => void;
}) {
  const tone = groupTone(group.group);
  // Plain border on every group card: the thick status-coloured left edge
  // (green when completed, blue otherwise) read as a stray highlight. The
  // group's own label still carries the status colour.
  return (
    <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 hover:bg-bg-secondary"
      >
        <div className="flex items-center gap-2">
          <IconChevronDown
            size={16}
            className={cn("text-ink-tertiary transition-transform", !expanded && "-rotate-90")}
          />
          <span className={cn("text-[13px] font-semibold", groupTextClass(tone))}>{group.label}</span>
          <span className="rounded-full bg-bg-tertiary px-2 py-0.5 text-[11px] font-medium text-ink-secondary">
            {group.count}
          </span>
          {group.overdue_count > 0 && (
            <span className="text-[11px] text-danger">{group.overdue_count} overdue</span>
          )}
        </div>
        <span className="text-[12px] text-ink-tertiary">Avg progress {group.avg_progress}%</span>
      </button>

      {expanded && (
        <div className="overflow-x-auto">
          <ColumnHeader gridTemplate={gridTemplate} />
          {group.items.map((item) => (
            <ActionRow
              key={item.id}
              projectId={projectId}
              item={item}
              gridTemplate={gridTemplate}
              selected={selected.has(item.id)}
              onSelect={() => onSelect(item.id)}
              onExpand={() => onExpand(item.id)}
              expanded={expandedRows.has(item.id)}
              detail={detailMap[item.id]}
              canManage={canManage}
              onStatusChange={onStatusChange}
              onPriorityChange={onPriorityChange}
              onOwnerChange={onOwnerChange}
              onDueChange={onDueChange}
              onArchive={() => onArchive(item.id, item.lock_version)}
              onRestore={() => onRestore(item.id)}
              onSubtaskStatusChange={onSubtaskStatusChange}
              onSubtaskFieldChange={onSubtaskFieldChange}
              onSubtaskArchive={onSubtaskArchive}
              onAddSubtask={onAddSubtask}
              members={members}
            />
          ))}

          {adding && (
            <div
              className="grid items-center gap-2 border-b border-line-tertiary bg-bg-secondary/30 px-3 py-2"
              style={{ gridTemplateColumns: gridTemplate }}
            >
              <div />
              <div className="flex min-w-0 items-center gap-2">
                <IconPlus size={14} className="text-ink-tertiary" />
                <input
                  type="text"
                  value={newActionTitle}
                  onChange={(e) => setNewActionTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onSubmitNewAction(group.group, newActionTitle);
                    if (e.key === "Escape") onCancelAdd();
                  }}
                  placeholder="New action"
                  autoFocus
                  className="min-w-0 flex-1 rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary outline-none focus:border-brand-500"
                />
              </div>
              <div className="col-span-full mt-1 flex gap-2">
                <button
                  type="button"
                  onClick={() => onSubmitNewAction(group.group, newActionTitle)}
                  className="rounded bg-brand-500 px-2 py-1 text-[12px] text-white hover:bg-brand-600"
                >
                  Add
                </button>
                <button
                  type="button"
                  onClick={onCancelAdd}
                  className="rounded px-2 py-1 text-[12px] text-ink-secondary hover:bg-bg-secondary"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-line-tertiary px-3 py-2">
            {canManage ? (
              <button
                type="button"
                onClick={onAddAction}
                className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-600 hover:text-brand-700"
              >
                <IconPlus size={14} /> Add action
              </button>
            ) : (
              <span />
            )}
            <span className="text-[12px] text-ink-tertiary">
              Avg progress: {group.avg_progress}% · {group.count} {group.count === 1 ? "action" : "actions"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}