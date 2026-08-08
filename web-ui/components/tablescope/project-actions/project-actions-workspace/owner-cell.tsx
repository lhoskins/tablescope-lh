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
} from "@tabler/icons-react";import { Avatar } from "./avatar";



export function OwnerCell({
  value,
  members,
  canManage,
  onChange,
}: {
  value: number | null;
  members: { user_id: number; display_name: string | null; email: string }[];
  canManage: boolean;
  onChange: (v: number | null) => void;
}) {
  const selected = members.find((m) => m.user_id === value);
  const name = selected ? selected.display_name || selected.email : "Unassigned";
  if (!canManage) {
    return (
      <div className="flex min-w-0 items-center gap-1.5">
        <Avatar name={name} />
        <span className="truncate text-[12px] text-ink-primary">{name}</span>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Avatar name={name} />
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        onClick={(e) => e.stopPropagation()}
        className="min-w-0 flex-1 appearance-none border-0 bg-transparent py-0.5 pr-4 text-[12px] text-ink-primary outline-none"
      >
        <option value="">Unassigned</option>
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.display_name || m.email}
          </option>
        ))}
      </select>
      <IconChevronDown size={12} className="pointer-events-none -ml-4 text-ink-tertiary" />
    </div>
  );
}