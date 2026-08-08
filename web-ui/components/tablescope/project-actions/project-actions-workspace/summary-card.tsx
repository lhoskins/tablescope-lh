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


export function SummaryCard({
  value,
  label,
  icon: Icon,
  tone,
}: {
  value: string | number;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string; stroke?: number }>;
  tone: "brand" | "danger" | "success";
}) {
  const toneClass =
    tone === "brand" ? "text-brand-600" : tone === "danger" ? "text-danger" : "text-success";
  return (
    <div className="flex flex-col rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <Icon size={20} className={cn("mb-2", toneClass)} stroke={1.5} />
      <div className="text-2xl font-semibold text-ink-primary">{value}</div>
      <div className="text-[12px] text-ink-secondary">{label}</div>
    </div>
  );
}