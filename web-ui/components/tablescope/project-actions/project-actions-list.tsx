"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { IconClipboardList, IconLoader2, IconPlus, IconSearch } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  projectActionsApi,
  type ProjectActionListItem,
  type ProjectActionPriority,
  type ProjectActionStatus,
} from "@/lib/api/project-actions";

const STATUS_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  blocked: "Blocked",
  completed: "Completed",
  cancelled: "Cancelled",
};

const PRIORITY_VARIANTS: Record<ProjectActionPriority, "success" | "neutral" | "warning" | "danger"> = {
  low: "success",
  medium: "neutral",
  high: "warning",
  critical: "danger",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

export function ProjectActionsList({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState<ProjectActionStatus | "">("");
  const [priority, setPriority] = useState<ProjectActionPriority | "">("");
  const [q, setQ] = useState("");
  const [overdue, setOverdue] = useState<boolean | undefined>(undefined);

  const { data, isLoading } = useQuery({
    queryKey: ["project", projectId, "actions", { status, priority, q, overdue }],
    queryFn: () =>
      projectActionsApi.list(projectId, {
        status: status || undefined,
        priority: priority || undefined,
        q: q || undefined,
        overdue,
      }),
  });

  const items = data?.items ?? [];

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1">
        <IconSearch size={14} className="text-ink-tertiary" />
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search actions"
          className="bg-transparent text-[13px] text-ink-primary outline-none"
        />
      </div>
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value as ProjectActionStatus | "")}
        className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
      >
        <option value="">All statuses</option>
        {Object.entries(STATUS_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      <select
        value={priority}
        onChange={(e) => setPriority(e.target.value as ProjectActionPriority | "")}
        className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
      >
        <option value="">All priorities</option>
        <option value="critical">Critical</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
      <label className="flex items-center gap-1 text-[13px] text-ink-secondary">
        <input
          type="checkbox"
          checked={overdue === true}
          onChange={(e) => setOverdue(e.target.checked ? true : undefined)}
        />
        Overdue only
      </label>
    </div>
  );

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-actions"
      breadcrumbLabel="Project Actions"
      actions={toolbar}
    >
      <div className="space-y-3">
        {isLoading ? (
          <div className="flex items-center gap-2 py-8 text-small text-ink-tertiary">
            <IconLoader2 size={16} className="animate-spin" />
            Loading actions…
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-line-tertiary bg-bg-primary py-16 text-center">
            <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-500">
              <IconClipboardList size={22} />
            </div>
            <p className="text-[13px] text-ink-secondary">
              No project actions yet. Create one from an Insight card.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-line-tertiary rounded-lg border border-line-tertiary bg-bg-primary">
            {items.map((action) => (
              <ActionRow key={action.id} action={action} projectId={projectId} />
            ))}
          </div>
        )}
      </div>
    </ProjectShell>
  );
}

function ActionRow({ action, projectId }: { action: ProjectActionListItem; projectId: string }) {
  return (
    <Link
      href={`/projects/${projectId}/actions/${action.id}`}
      className="group flex items-center justify-between gap-4 px-4 py-3 transition-colors hover:bg-bg-secondary"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-ink-primary">
            {action.title}
          </span>
          <Badge tone={PRIORITY_VARIANTS[action.priority] ?? "default"} size="sm">
            {action.priority}
          </Badge>
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-[12px] text-ink-tertiary">
          <span>{STATUS_LABELS[action.status] ?? action.status}</span>
          {action.percent_complete > 0 && (
            <span>{action.percent_complete}%</span>
          )}
          {action.owner_name && <span>Owner: {action.owner_name}</span>}
          {action.due_date && <span>Due {formatDate(action.due_date)}</span>}
        </div>
      </div>
      <div className="shrink-0 text-[12px] text-ink-tertiary">
        {action.active_subtasks}/{action.total_subtasks} subtasks
      </div>
    </Link>
  );
}
