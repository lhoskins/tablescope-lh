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
import { PRIORITY_LABELS } from "./priority-labels";
import { SORT_OPTIONS } from "./sort-options";
import { GROUP_BY_OPTIONS } from "./group-by-options";



export function Toolbar({
  search,
  setSearch,
  filters,
  setFilters,
  prefs,
  savePrefs,
  members,
  canManage,
  onNewAction,
}: {
  search: string;
  setSearch: (v: string) => void;
  filters: ProjectActionFilters;
  setFilters: React.Dispatch<React.SetStateAction<ProjectActionFilters>>;
  prefs: { groupBy: ProjectActionGroupBy; sortBy: ProjectActionSortBy; sortDirection: "asc" | "desc" };
  savePrefs: (next: { groupBy?: ProjectActionGroupBy; sortBy?: ProjectActionSortBy; sortDirection?: "asc" | "desc" }) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  canManage: boolean;
  onNewAction: () => void;
}) {
  const ownerValue = filters.owner_user_id != null ? String(filters.owner_user_id) : "";
  const statusValue = filters.status ?? "";
  const priorityValue = filters.priority ?? "";
  const overdueChecked = filters.overdue === true;
  const sortValue = `${prefs.sortBy}:${prefs.sortDirection}`;

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <IconSearch
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search actions"
            className="h-8 w-48 rounded-md border border-line-tertiary bg-bg-primary pl-8 pr-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          />
        </div>
        <select
          value={ownerValue}
          onChange={(e) => {
            const v = e.target.value;
            setFilters((prev) => ({ ...prev, owner_user_id: v ? Number(v) : undefined }));
          }}
          className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        >
          <option value="">All owners</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.display_name || m.email}
            </option>
          ))}
        </select>
        <select
          value={statusValue}
          onChange={(e) =>
            setFilters((prev) => ({ ...prev, status: (e.target.value as ProjectActionStatus) || undefined }))
          }
          className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={priorityValue}
          onChange={(e) =>
            setFilters((prev) => ({ ...prev, priority: (e.target.value as ProjectActionPriority) || undefined }))
          }
          className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        >
          <option value="">All priorities</option>
          {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <label className="inline-flex items-center gap-1.5 text-[13px] text-ink-secondary">
          <input
            type="checkbox"
            checked={overdueChecked}
            onChange={(e) =>
              setFilters((prev) => ({ ...prev, overdue: e.target.checked || undefined }))
            }
            className="rounded border-line-tertiary"
          />
          Overdue only
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 text-[13px] text-ink-secondary">
          <span className="text-ink-tertiary">Group by</span>
          <select
            value={prefs.groupBy}
            onChange={(e) => savePrefs({ groupBy: e.target.value as ProjectActionGroupBy })}
            className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          >
            {GROUP_BY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-1 text-[13px] text-ink-secondary">
          <span className="text-ink-tertiary">Sort by</span>
          <select
            value={sortValue}
            onChange={(e) => {
              const [sortBy, sortDirection] = e.target.value.split(":");
              savePrefs({ sortBy: sortBy as ProjectActionSortBy, sortDirection: sortDirection as "asc" | "desc" });
            }}
            className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <Button variant="primary" size="sm" onClick={onNewAction} disabled={!canManage}>
          <IconPlus size={14} /> New action
        </Button>
      </div>
    </div>
  );
}