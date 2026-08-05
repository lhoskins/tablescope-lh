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
import { SubtaskRow } from "./subtask-row";



export function SubtaskPanel({
  actionId,
  subtasks,
  canManage,
  onStatusChange,
  onFieldChange,
  onArchive,
  onAddSubtask,
  members,
}: {
  actionId: number;
  subtasks: ProjectActionSubtask[];
  canManage: boolean;
  onStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const [newTitle, setNewTitle] = useState("");

  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-ink-primary">Subitems</h3>
        <span className="text-[12px] text-ink-tertiary">{subtasks.length} subitems</span>
      </div>
      <div className="space-y-1">
        <div
          className="grid items-center gap-2 border-b border-line-tertiary bg-bg-secondary/50 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary"
          style={{ gridTemplateColumns: SUBTASK_GRID }}
        >
          <div />
          <div>Subitem</div>
          <div>Owner</div>
          <div>Status</div>
          <div>Due date</div>
          <div>Effort</div>
          <div className="text-center">Completed</div>
          <div className="text-right">Actions</div>
        </div>

        {subtasks.map((sub) => (
          <SubtaskRow
            key={sub.id}
            actionId={actionId}
            subtask={sub}
            canManage={canManage}
            onStatusChange={onStatusChange}
            onFieldChange={onFieldChange}
            onArchive={() => onArchive(actionId, sub.id)}
            members={members}
          />
        ))}

        {canManage && (
          <div className="flex items-center gap-2 pt-2">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTitle.trim()) {
                  onAddSubtask(actionId, newTitle.trim());
                  setNewTitle("");
                }
                if (e.key === "Escape") setNewTitle("");
              }}
              placeholder="New subitem"
              className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary outline-none focus:border-brand-500"
            />
            <Button
              size="sm"
              onClick={() => {
                if (newTitle.trim()) {
                  onAddSubtask(actionId, newTitle.trim());
                  setNewTitle("");
                }
              }}
            >
              <IconPlus size={14} /> Add
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}