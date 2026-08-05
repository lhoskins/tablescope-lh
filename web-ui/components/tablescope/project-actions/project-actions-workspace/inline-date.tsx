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
} from "@tabler/icons-react";import { formatDateShort } from "./format-date-short";



export function InlineDate({
  value,
  canManage,
  onChange,
}: {
  value: string | null;
  canManage: boolean;
  onChange: (v: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value) || "mm/dd/yyyy";
  if (canManage && editing) {
    return (
      <input
        type="date"
        value={value ? value.split("T")[0] : ""}
        onChange={(e) => onChange(e.target.value || null)}
        onClick={(e) => e.stopPropagation()}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
        autoFocus
        className="rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-[12px] text-ink-primary outline-none focus:border-brand-500"
      />
    );
  }
  return (
    <button
      type="button"
      disabled={!canManage}
      onClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
      className="truncate rounded px-1 py-0.5 text-left text-[12px] text-ink-secondary disabled:cursor-default disabled:hover:bg-transparent hover:bg-bg-secondary"
    >
      {display}
    </button>
  );
}