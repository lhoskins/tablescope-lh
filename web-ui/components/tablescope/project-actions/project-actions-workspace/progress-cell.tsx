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
} from "@tabler/icons-react";


export function ProgressCell({
  percent,
  completed,
  total,
  status,
}: {
  percent: number;
  completed: number;
  total: number;
  status: ProjectActionStatus;
}) {
  const segments = Math.max(total || 1, 1);
  const completedColor =
    status === "completed"
      ? "bg-emerald-500"
      : status === "in_progress"
        ? "bg-amber-500"
        : status === "blocked"
          ? "bg-red-500"
          : "bg-brand-500";
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-2">
        <div className="flex flex-1 gap-0.5">
          {Array.from({ length: segments }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "h-2 flex-1 rounded-sm",
                i < (completed || 0) ? completedColor : "bg-bg-tertiary",
              )}
            />
          ))}
        </div>
        <span className="w-8 text-right text-[12px] font-semibold text-ink-primary">{percent}%</span>
      </div>
      {total > 0 && (
        <span className="text-[11px] text-ink-tertiary">
          {completed} of {total} subtasks
        </span>
      )}
    </div>
  );
}