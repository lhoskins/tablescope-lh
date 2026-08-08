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
} from "@tabler/icons-react";import { isOverdue } from "./is-overdue";
import { SubtaskPanel } from "./subtask-panel";
import { ProgressCell } from "./progress-cell";
import { DueCell } from "./due-cell";
import { PriorityCell } from "./priority-cell";
import { OwnerCell } from "./owner-cell";
import { StatusCell } from "./status-cell";
import { RiskCell } from "./risk-cell";
import { SourceCell } from "./source-cell";
import { RowMenu } from "./row-menu";



export function ActionRow({
  projectId,
  item,
  gridTemplate,
  selected,
  onSelect,
  onExpand,
  expanded,
  detail,
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
}: {
  projectId: string;
  item: ProjectActionListItem;
  gridTemplate: string;
  selected: boolean;
  onSelect: () => void;
  onExpand: () => void;
  expanded: boolean;
  detail: ProjectAction | undefined;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner_user_id: number | null, version: number) => void;
  onDueChange: (id: number, due_date: string | null, version: number) => void;
  onArchive: () => void;
  onRestore: () => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const progress = item.percent_complete ?? 0;
  const overdue = isOverdue(item);
  const activeSubtasks = detail?.subtasks.filter((s) => !s.archived_at) ?? [];

  return (
    <div className="border-b border-line-tertiary last:border-b-0">
      <div
        className="grid cursor-pointer items-center gap-2 px-3 py-2.5 transition-colors hover:bg-bg-secondary"
        style={{ gridTemplateColumns: gridTemplate }}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("button, select, input, a, textarea")) return;
          onExpand();
        }}
      >
        <div className="flex items-center justify-center">
          <input
            type="checkbox"
            checked={selected}
            onChange={onSelect}
            onClick={(e) => e.stopPropagation()}
            aria-label={`Select ${item.title}`}
          />
        </div>

        <div className="flex min-w-0 flex-col">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExpand();
              }}
              className="shrink-0"
              aria-label={expanded ? "Collapse subtasks" : "Expand subtasks"}
            >
              <IconChevronRight
                size={14}
                className={cn("text-ink-tertiary transition-transform", expanded && "rotate-90")}
              />
            </button>
            <Link
              href={`/projects/${projectId}/actions/${item.id}`}
              onClick={(e) => e.stopPropagation()}
              className="truncate text-[13px] font-semibold text-ink-primary hover:text-brand-600 hover:underline"
            >
              {item.title}
            </Link>
          </div>
          {item.description && (
            <span className="truncate pl-5 text-[12px] text-ink-tertiary">{item.description}</span>
          )}
          <div className="flex items-center gap-3 pl-5 pt-1">
            {item.comment_count > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-ink-tertiary">
                <IconMessage size={12} /> {item.comment_count}
              </span>
            )}
            {item.total_subtasks > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-ink-tertiary">
                <IconClipboardList size={12} /> {item.total_subtasks}
              </span>
            )}
          </div>
        </div>

        <OwnerCell
          value={item.owner_user_id}
          members={members}
          canManage={canManage}
          onChange={(v) => onOwnerChange(item.id, v, item.lock_version)}
        />
        <StatusCell
          value={item.status}
          canManage={canManage}
          onChange={(v) => onStatusChange(item.id, v, item.lock_version)}
        />
        <PriorityCell
          value={item.priority}
          canManage={canManage}
          onChange={(v) => onPriorityChange(item.id, v, item.lock_version)}
        />
        <ProgressCell
          percent={progress}
          completed={item.completed_required_subtasks}
          total={item.required_subtasks}
          status={item.status}
        />
        <DueCell
          value={item.due_date}
          overdue={overdue}
          canManage={canManage}
          onChange={(v) => onDueChange(item.id, v, item.lock_version)}
        />
        <RiskCell impact={item.risk_impact} />
        <SourceCell item={item} />
        <div className="truncate text-[12px] text-ink-tertiary">{timeAgo(item.updated_at)}</div>
        <RowMenu projectId={projectId} item={item} canManage={canManage} onArchive={onArchive} onRestore={onRestore} />
      </div>

      {expanded && (
        <div className="border-t border-line-tertiary bg-bg-secondary/50 px-8 py-4">
          <SubtaskPanel
            actionId={item.id}
            subtasks={activeSubtasks}
            canManage={canManage}
            onStatusChange={onSubtaskStatusChange}
            onFieldChange={onSubtaskFieldChange}
            onArchive={onSubtaskArchive}
            onAddSubtask={onAddSubtask}
            members={members}
          />
        </div>
      )}
    </div>
  );
}