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



export function SourceCell({ item }: { item: ProjectActionListItem }) {
  const title = item.source_insight_title;
  if (!title) {
    return (
      <span className="text-[12px] text-ink-tertiary">{SOURCE_TYPE_LABELS[item.source_type] ?? item.source_type}</span>
    );
  }
  const href = item.source_insight_id
    ? `/business-insight/analysis/${encodeURIComponent(item.source_insight_id)}`
    : undefined;
  const content = (
    <span className="inline-flex items-center gap-1 truncate text-[12px]">
      <IconSparkles size={12} className="shrink-0 text-brand-500" />
      <span className="truncate">{title}</span>
    </span>
  );
  if (href) {
    return (
      <Link href={href} className="text-brand-600 hover:underline" onClick={(e) => e.stopPropagation()}>
        {content}
      </Link>
    );
  }
  return <span className="text-ink-secondary">{content}</span>;
}