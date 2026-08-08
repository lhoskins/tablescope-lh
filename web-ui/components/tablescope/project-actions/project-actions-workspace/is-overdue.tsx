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


export function isOverdue(item: {
  due_date: string | null;
  status: string;
  archived_at?: string | null;
}): boolean {
  if (!item.due_date || item.archived_at) return false;
  if (["completed", "cancelled"].includes(item.status)) return false;
  return new Date(item.due_date) < new Date();
}