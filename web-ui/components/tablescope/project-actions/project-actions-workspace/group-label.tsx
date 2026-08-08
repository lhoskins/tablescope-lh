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
} from "@tabler/icons-react";import { SOURCE_TYPE_LABELS } from "./source-type-labels";
import { GROUP_LABELS } from "./group-labels";
import { DUE_STATE_ORDER } from "./due-state-order";



export function groupLabel(
  group: string,
  groupBy: ProjectActionGroupBy,
  members: { user_id: number; display_name: string | null; email: string }[],
): string {
  if (groupBy === "owner") {
    if (group === "unassigned") return "Unassigned";
    const m = members.find((m) => String(m.user_id) === group);
    return m?.display_name || m?.email || group;
  }
  if (groupBy === "due_state") {
    return DUE_STATE_ORDER[group] !== undefined ? GROUP_LABELS[group] || group : group;
  }
  if (groupBy === "source_type") return SOURCE_TYPE_LABELS[group] || group;
  return GROUP_LABELS[group] || group;
}