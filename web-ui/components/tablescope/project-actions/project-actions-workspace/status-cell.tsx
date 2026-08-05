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
} from "@tabler/icons-react";import { STATUS_BADGE_LABELS } from "./status-badge-labels";
import { STATUS_COLORS } from "./status-colors";



export function StatusCell({
  value,
  canManage,
  onChange,
}: {
  value: ProjectActionStatus;
  canManage: boolean;
  onChange: (v: ProjectActionStatus) => void;
}) {
  const color = STATUS_COLORS[value];
  if (!canManage) {
    return (
      <span className={cn("inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium", color)}>
        {STATUS_BADGE_LABELS[value]}
      </span>
    );
  }
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ProjectActionStatus)}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "w-full appearance-none rounded-full border-0 py-1 pl-2.5 pr-6 text-[11px] font-medium outline-none",
          color,
        )}
      >
        {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      <IconChevronDown
        size={12}
        className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-current opacity-70"
      />
    </div>
  );
}