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
} from "@tabler/icons-react";import { PRIORITY_LABELS } from "./priority-labels";
import { PRIORITY_TEXT_COLORS } from "./priority-text-colors";



export function PriorityCell({
  value,
  canManage,
  onChange,
}: {
  value: ProjectActionPriority;
  canManage: boolean;
  onChange: (v: ProjectActionPriority) => void;
}) {
  const color = PRIORITY_TEXT_COLORS[value];
  if (!canManage) {
    return <span className={cn("text-[12px] font-medium", color)}>{PRIORITY_LABELS[value]}</span>;
  }
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ProjectActionPriority)}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "w-full appearance-none border-0 bg-transparent py-1 pr-6 text-[12px] font-medium outline-none",
          color,
        )}
      >
        {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      <IconChevronDown
        size={12}
        className={cn("pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 opacity-70", color)}
      />
    </div>
  );
}