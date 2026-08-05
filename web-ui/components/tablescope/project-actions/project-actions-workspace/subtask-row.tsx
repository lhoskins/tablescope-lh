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
} from "@tabler/icons-react";import { SUBTASK_GRID } from "./subtask-grid";
import { OwnerCell } from "./owner-cell";
import { StatusCell } from "./status-cell";
import { InlineDate } from "./inline-date";



export function SubtaskRow({
  actionId,
  subtask,
  canManage,
  onStatusChange,
  onFieldChange,
  onArchive,
  members,
}: {
  actionId: number;
  subtask: ProjectActionSubtask;
  canManage: boolean;
  onStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onArchive: () => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const completed = subtask.status === "completed";
  const [title, setTitle] = useState(subtask.title);

  useEffect(() => {
    setTitle(subtask.title);
  }, [subtask.title]);

  return (
    <div
      className="grid items-center gap-2 rounded-md border border-line-tertiary px-2 py-1.5"
      style={{ gridTemplateColumns: SUBTASK_GRID }}
    >
      <div />
      {canManage ? (
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title !== subtask.title && onFieldChange(actionId, subtask.id, { title })}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              title !== subtask.title && onFieldChange(actionId, subtask.id, { title });
              (e.target as HTMLInputElement).blur();
            }
          }}
          className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        />
      ) : (
        <span className="text-[13px] text-ink-primary">{subtask.title}</span>
      )}

      <OwnerCell
        value={subtask.owner_user_id}
        members={members}
        canManage={canManage}
        onChange={(v) => onFieldChange(actionId, subtask.id, { owner_user_id: v })}
      />
      <StatusCell
        value={subtask.status}
        canManage={canManage}
        onChange={(v) => onStatusChange(actionId, subtask.id, v)}
      />
      <InlineDate
        value={subtask.due_date}
        canManage={canManage}
        onChange={(v) => onFieldChange(actionId, subtask.id, { due_date: v })}
      />
      <input
        type="number"
        min={1}
        max={10}
        value={subtask.effort_points ?? ""}
        disabled={!canManage}
        onChange={(e) => {
          const v = e.target.value ? Number(e.target.value) : null;
          onFieldChange(actionId, subtask.id, { effort_points: v });
        }}
        placeholder="-"
        className="w-full rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-center text-[12px] text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
      />
      <div className="flex items-center justify-center">
        <input
          type="checkbox"
          checked={completed}
          disabled={!canManage}
          onChange={(e) =>
            onStatusChange(actionId, subtask.id, e.target.checked ? "completed" : "not_started")
          }
          aria-label={`Mark ${subtask.title} complete`}
        />
      </div>
      {canManage && (
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={onArchive}
            className="text-ink-tertiary hover:text-danger"
            aria-label={`Archive ${subtask.title}`}
          >
            <IconTrash size={14} />
          </button>
        </div>
      )}
    </div>
  );
}