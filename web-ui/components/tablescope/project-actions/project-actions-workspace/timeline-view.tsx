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
} from "@tabler/icons-react";import { ColumnHeader } from "./column-header";
import { ActionRow } from "./action-row";



export function TimelineView({
  projectId,
  items,
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
}: {
  projectId: string;
  items: ProjectActionListItem[];
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
    payload: Partial<{
      title: string;
      owner_user_id: number | null;
      due_date: string | null;
      effort_points: number | null;
    }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const sections = useMemo(() => {
    const groups: Record<string, { label: string; sort: number; items: ProjectActionListItem[] }> = {};
    for (const item of items) {
      let key: string;
      let label: string;
      let sort: number;
      if (!item.due_date) {
        key = "no-due";
        label = "No due date";
        sort = Number.MAX_SAFE_INTEGER;
      } else {
        const d = new Date(item.due_date);
        key = `${d.getFullYear()}-${d.getMonth()}`;
        label = d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
        sort = d.getFullYear() * 12 + d.getMonth();
      }
      if (!groups[key]) groups[key] = { label, sort, items: [] };
      groups[key].items.push(item);
    }
    return Object.values(groups).sort((a, b) => a.sort - b.sort);
  }, [items]);

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <div key={section.label} className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
          <h3 className="mb-3 text-[13px] font-semibold text-ink-primary">{section.label}</h3>
          <div className="overflow-x-auto">
            <ColumnHeader gridTemplate={gridTemplate} />
            {section.items.map((item) => (
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
          </div>
        </div>
      ))}
    </div>
  );
}