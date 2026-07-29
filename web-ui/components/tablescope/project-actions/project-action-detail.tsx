"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import { initials } from "@/lib/ui/format";
import {
  IconLoader2,
  IconPlus,
  IconTrash,
  IconArchive,
  IconSparkles,
  IconChevronDown,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { useToasts } from "@/components/ui/toast";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { canManageProjectActions } from "@/lib/auth";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import {
  projectActionsApi,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
} from "@/lib/api/project-actions";

const STATUS_BADGE_LABELS: Record<ProjectActionStatus, string> = {
  not_started: "Not started",
  in_progress: "Working on it",
  blocked: "Blocked",
  completed: "Done",
  cancelled: "Cancelled",
};

const STATUS_COLORS: Record<ProjectActionStatus, string> = {
  not_started: "bg-bg-tertiary text-ink-secondary",
  in_progress: "bg-warning-bg text-warning",
  blocked: "bg-danger-bg text-danger",
  completed: "bg-success-bg text-success",
  cancelled: "bg-bg-tertiary text-ink-tertiary",
};

const PRIORITY_LABELS: Record<ProjectActionPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

function inputToDate(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
}

function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function Avatar({ name, size = "sm" }: { name: string; size?: "sm" | "md" }) {
  const sizeClass = size === "sm" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-[11px]";
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-brand-50 font-semibold text-brand-700",
        sizeClass,
      )}
      aria-hidden
    >
      {initials(name || "?")}
    </div>
  );
}

export function ProjectActionDetail({
  projectId,
  actionId,
}: {
  projectId: string;
  actionId: number;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { push: pushToast } = useToasts();
  const { data: identity } = useCurrentUser();
  const { data: members = [] } = useProjectMembers(projectId);
  const canEdit = canManageProjectActions(
    identity?.user?.rawRole,
    identity?.user?.isSuperAdmin,
  );

  const { data: action, isLoading } = useQuery({
    queryKey: ["project", projectId, "actions", actionId],
    queryFn: () => projectActionsApi.get(projectId, actionId),
  });

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<ProjectActionPriority>("medium");
  const [status, setStatus] = useState<ProjectActionStatus>("not_started");
  const [ownerUserId, setOwnerUserId] = useState<string>("");
  const [dueDate, setDueDate] = useState("");
  const [newSubtask, setNewSubtask] = useState("");

  useEffect(() => {
    if (!action) return;
    setTitle(action.title);
    setDescription(action.description ?? "");
    setPriority(action.priority);
    setStatus(action.status);
    setOwnerUserId(action.owner_user_id ? String(action.owner_user_id) : "");
    setDueDate(action.due_date ? action.due_date.split("T")[0] : "");
  }, [action]);

  const updateAction = useMutation({
    mutationFn: () =>
      projectActionsApi.update(projectId, actionId, {
        title,
        description: description || null,
        priority,
        status,
        owner_user_id: ownerUserId ? Number(ownerUserId) : null,
        due_date: inputToDate(dueDate),
        expected_version: action?.lock_version,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "actions"],
      });
      pushToast("Action updated", "success");
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  const archiveAction = useMutation({
    mutationFn: () => projectActionsApi.archive(projectId, actionId, action?.lock_version),
    onSuccess: () => {
      pushToast("Action archived", "success");
      router.push(`/projects/${projectId}/actions`);
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  const createSubtask = useMutation({
    mutationFn: (title: string) =>
      projectActionsApi.createSubtask(projectId, actionId, {
        title,
        status: "not_started",
        is_required: true,
      }),
    onSuccess: () => {
      setNewSubtask("");
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "actions", actionId],
      });
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  if (isLoading || !action) {
    return (
      <ProjectShell
        projectId={projectId}
        activeNav="project-actions"
        breadcrumbLabel="Action Detail"
      >
        <div className="flex items-center gap-2 py-8 text-[13px] text-ink-tertiary">
          <IconLoader2 size={16} className="animate-spin" />
          Loading…
        </div>
      </ProjectShell>
    );
  }

  const owner = members.find((m) => m.user_id === action.owner_user_id);
  const ownerName = owner ? owner.display_name || owner.email : "Unassigned";

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-actions"
      breadcrumbLabel="Action Detail"
      actions={
        canEdit && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => archiveAction.mutate()}
            disabled={archiveAction.isPending}
          >
            <IconArchive size={14} />
            Archive
          </Button>
        )
      }
    >
      <div className="mx-auto max-w-4xl space-y-6 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Badge tone={action.priority === "critical" ? "danger" : action.priority === "high" ? "warning" : "brand"} size="md">
              {PRIORITY_LABELS[action.priority]}
            </Badge>
            <span className="text-[13px] font-medium text-ink-secondary">{action.percent_complete}% complete</span>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[12px] font-medium text-ink-secondary">Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={!canEdit}
            className="w-full rounded-lg border border-line-tertiary bg-bg-primary px-4 py-3 text-lg font-semibold text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
            placeholder="Action title"
          />
        </div>

        <div className="space-y-2">
          <label className="text-[12px] font-medium text-ink-secondary">Description</label>
          <AutosizeTextarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={!canEdit}
            minRows={3}
            placeholder="Add a description..."
            className="w-full rounded-lg border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary disabled:bg-bg-secondary"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <LabeledSelect
            label="Priority"
            value={priority}
            onChange={(v) => setPriority(v as ProjectActionPriority)}
            disabled={!canEdit}
            options={Object.entries(PRIORITY_LABELS).map(([k, label]) => ({ value: k, label }))}
          />
          <LabeledSelect
            label="Status"
            value={status}
            onChange={(v) => setStatus(v as ProjectActionStatus)}
            disabled={!canEdit}
            options={Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => ({ value: k, label }))}
          />
          <LabeledSelect
            label="Owner"
            value={ownerUserId}
            onChange={(v) => setOwnerUserId(v)}
            disabled={!canEdit}
            options={[{ value: "", label: "Unassigned" }, ...members.map((m) => ({ value: String(m.user_id), label: m.display_name || m.email }))]}
          />
          <LabeledDate
            label="Due date"
            value={dueDate}
            onChange={(v) => setDueDate(v)}
            disabled={!canEdit}
          />
        </div>

        {canEdit && (
          <Button onClick={() => updateAction.mutate()} disabled={updateAction.isPending}>
            {updateAction.isPending ? "Saving…" : "Save action"}
          </Button>
        )}

        {action.source_insight_title && (
          <div className="rounded-lg border border-line-tertiary bg-bg-secondary/50 p-4">
            <h3 className="text-[12px] font-semibold text-ink-secondary">Source insight</h3>
            <Link
              href={
                action.source_insight_id
                  ? `/business-insight/analysis/${encodeURIComponent(action.source_insight_id)}`
                  : "#"
              }
              className="mt-1 inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-600 hover:underline"
            >
              <IconSparkles size={14} />
              {action.source_insight_title}
            </Link>
          </div>
        )}

        <div className="rounded-lg border border-line-tertiary bg-bg-primary p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-ink-primary">Subitems</h3>
            <span className="text-[12px] text-ink-tertiary">
              {action.subtasks.filter((s) => !s.archived_at).length} subitems
            </span>
          </div>

          <div className="space-y-2">
            {action.subtasks
              .filter((s) => !s.archived_at)
              .map((sub) => (
                <SubtaskRow
                  key={sub.id}
                  projectId={projectId}
                  actionId={actionId}
                  subtask={sub}
                  canEdit={canEdit}
                  members={members}
                />
              ))}

            {canEdit && (
              <div className="flex items-center gap-2 pt-2">
                <input
                  type="text"
                  value={newSubtask}
                  onChange={(e) => setNewSubtask(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newSubtask.trim()) {
                      createSubtask.mutate(newSubtask.trim());
                    }
                  }}
                  placeholder="New subitem"
                  className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
                />
                <Button
                  size="sm"
                  onClick={() => newSubtask.trim() && createSubtask.mutate(newSubtask.trim())}
                  disabled={createSubtask.isPending}
                >
                  <IconPlus size={14} /> Add
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </ProjectShell>
  );
}

function LabeledSelect({
  label,
  value,
  onChange,
  disabled,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-[12px] font-medium text-ink-secondary">{label}</label>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className="w-full appearance-none rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 pr-8 text-[13px] text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <IconChevronDown size={14} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-ink-tertiary" />
      </div>
    </div>
  );
}

function LabeledDate({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value || null) || "-";
  return (
    <div className="space-y-1.5">
      <label className="text-[12px] font-medium text-ink-secondary">{label}</label>
      {editing ? (
        <input
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => setEditing(false)}
          onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
          disabled={disabled}
          autoFocus
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
        />
      ) : (
        <button
          type="button"
          disabled={disabled}
          onClick={() => setEditing(true)}
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-left text-[13px] text-ink-primary disabled:cursor-default disabled:bg-bg-secondary hover:bg-bg-secondary"
        >
          {display}
        </button>
      )}
    </div>
  );
}

function SubtaskRow({
  projectId,
  actionId,
  subtask,
  canEdit,
  members,
}: {
  projectId: string;
  actionId: number;
  subtask: ProjectActionSubtask;
  canEdit: boolean;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const queryClient = useQueryClient();
  const { push: pushToast } = useToasts();
  const [title, setTitle] = useState(subtask.title);

  useEffect(() => {
    setTitle(subtask.title);
  }, [subtask.title]);

  const update = useMutation({
    mutationFn: (payload: {
      title?: string;
      status?: ProjectActionStatus;
      owner_user_id?: number | null;
      due_date?: string | null;
      effort_points?: number | null;
    }) =>
      projectActionsApi.updateSubtask(projectId, actionId, subtask.id, {
        ...payload,
        expected_version: subtask.lock_version,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "actions", actionId],
      });
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  const archive = useMutation({
    mutationFn: () => projectActionsApi.archiveSubtask(projectId, actionId, subtask.id, subtask.lock_version),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "actions", actionId],
      });
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  const completed = subtask.status === "completed";
  const owner = members.find((m) => m.user_id === subtask.owner_user_id);
  const ownerName = owner ? owner.display_name || owner.email : "Unassigned";

  return (
    <div className="grid grid-cols-[1fr_120px_110px_70px_44px_32px] items-center gap-2 rounded-md border border-line-tertiary bg-bg-primary px-3 py-2">
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={completed}
          disabled={!canEdit}
          onChange={(e) =>
            update.mutate({ status: e.target.checked ? "completed" : "not_started" })
          }
          aria-label={`Mark ${subtask.title} complete`}
        />
        {canEdit ? (
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => title !== subtask.title && update.mutate({ title })}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                title !== subtask.title && update.mutate({ title });
                (e.target as HTMLInputElement).blur();
              }
            }}
            className="min-w-0 flex-1 rounded border border-line-tertiary bg-bg-primary px-2 py-0.5 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          />
        ) : (
          <span className="text-[13px] text-ink-primary">{subtask.title}</span>
        )}
      </div>

      <div className="flex min-w-0 items-center gap-1.5">
        <Avatar name={ownerName} size="sm" />
        {canEdit ? (
          <select
            value={subtask.owner_user_id ?? ""}
            onChange={(e) => update.mutate({ owner_user_id: e.target.value ? Number(e.target.value) : null })}
            className="min-w-0 flex-1 appearance-none border-0 bg-transparent text-[12px] text-ink-primary outline-none"
          >
            <option value="">Unassigned</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name || m.email}
              </option>
            ))}
          </select>
        ) : (
          <span className="truncate text-[12px] text-ink-primary">{ownerName}</span>
        )}
      </div>

      <div className="relative">
        <select
          value={subtask.status}
          disabled={!canEdit}
          onChange={(e) => update.mutate({ status: e.target.value as ProjectActionStatus })}
          className={cn(
            "w-full appearance-none rounded-full border-0 py-1 pl-2.5 pr-6 text-[11px] font-medium outline-none",
            STATUS_COLORS[subtask.status],
          )}
        >
          {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <IconChevronDown size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-current opacity-70" />
      </div>

      <InlineDate
        value={subtask.due_date}
        canEdit={canEdit}
        onChange={(v) => update.mutate({ due_date: v })}
      />

      <div className="flex items-center justify-center">
        <input
          type="checkbox"
          checked={completed}
          disabled={!canEdit}
          onChange={(e) => update.mutate({ status: e.target.checked ? "completed" : "not_started" })}
          aria-label={`Mark ${subtask.title} complete`}
        />
      </div>

      {canEdit && (
        <button
          type="button"
          onClick={() => archive.mutate()}
          className="text-ink-tertiary hover:text-danger"
          aria-label="Archive subtask"
        >
          <IconTrash size={14} />
        </button>
      )}
    </div>
  );
}

function InlineDate({
  value,
  canEdit,
  onChange,
}: {
  value: string | null;
  canEdit: boolean;
  onChange: (v: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value) || "-";
  if (canEdit && editing) {
    return (
      <input
        type="date"
        value={value ? value.split("T")[0] : ""}
        onChange={(e) => onChange(e.target.value || null)}
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
      disabled={!canEdit}
      onClick={() => setEditing(true)}
      className="truncate rounded px-1 py-0.5 text-left text-[12px] text-ink-secondary disabled:cursor-default disabled:hover:bg-transparent hover:bg-bg-secondary"
    >
      {display}
    </button>
  );
}
