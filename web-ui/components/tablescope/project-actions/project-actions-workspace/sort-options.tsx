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


export const SORT_OPTIONS: {
  key: string;
  label: string;
  sortBy: ProjectActionSortBy;
  sortDirection: "asc" | "desc";
}[] = [
  { key: "updated:desc", label: "Updated (newest)", sortBy: "updated", sortDirection: "desc" },
  { key: "updated:asc", label: "Updated (oldest)", sortBy: "updated", sortDirection: "asc" },
  { key: "created:desc", label: "Created (newest)", sortBy: "created", sortDirection: "desc" },
  { key: "due_date:asc", label: "Due date (soonest)", sortBy: "due_date", sortDirection: "asc" },
  { key: "priority:asc", label: "Priority (high first)", sortBy: "priority", sortDirection: "asc" },
  { key: "progress:desc", label: "Progress (most complete)", sortBy: "progress", sortDirection: "desc" },
  { key: "title:asc", label: "Title (A–Z)", sortBy: "title", sortDirection: "asc" },
];