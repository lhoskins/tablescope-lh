"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconLoader2, IconPlus, IconTrash, IconArchive } from "@tabler/icons-react";
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
  type ProjectAction,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
} from "@/lib/api/project-actions";

const STATUS_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  blocked: "Blocked",
  completed: "Completed",
  cancelled: "Cancelled",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toISOString().split("T")[0] ?? "";
}

function inputToDate(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
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
    setDueDate(formatDate(action.due_date));
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
    mutationFn: () => projectActionsApi.archive(projectId, actionId),
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
        <div className="flex items-center gap-2 py-8 text-small text-ink-tertiary">
          <IconLoader2 size={16} className="animate-spin" />
          Loading…
        </div>
      </ProjectShell>
    );
  }

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
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Badge tone={action.priority === "critical" ? "danger" : action.priority === "high" ? "warning" : "neutral"} size="md">
            {action.priority}
          </Badge>
          <span className="text-small text-ink-tertiary">
            {action.percent_complete}% complete
          </span>
        </div>

        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          disabled={!canEdit}
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-h4 font-semibold text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
        />

        <AutosizeTextarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={!canEdit}
          minRows={3}
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary disabled:bg-bg-secondary"
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <div>
            <label className="text-caption text-ink-secondary">Priority</label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as ProjectActionPriority)}
              disabled={!canEdit}
              className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary disabled:bg-bg-secondary"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <div>
            <label className="text-caption text-ink-secondary">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as ProjectActionStatus)}
              disabled={!canEdit}
              className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary disabled:bg-bg-secondary"
            >
              {Object.entries(STATUS_LABELS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-caption text-ink-secondary">Owner</label>
            <select
              value={ownerUserId}
              onChange={(e) => setOwnerUserId(e.target.value)}
              disabled={!canEdit}
              className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary disabled:bg-bg-secondary"
            >
              <option value="">No owner</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name || m.email}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-caption text-ink-secondary">Due date</label>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              disabled={!canEdit}
              className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary disabled:bg-bg-secondary"
            />
          </div>
        </div>

        {canEdit && (
          <Button onClick={() => updateAction.mutate()} disabled={updateAction.isPending}>
            {updateAction.isPending ? "Saving…" : "Save action"}
          </Button>
        )}

        <div className="rounded-lg border border-line-tertiary bg-bg-secondary/50 p-4">
          <h3 className="text-[13px] font-medium text-ink-primary">Subtasks</h3>
          <div className="mt-3 space-y-2">
            {action.subtasks.map((sub) => (
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
                  placeholder="New subtask"
                  className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newSubtask.trim()) {
                      createSubtask.mutate(newSubtask.trim());
                    }
                  }}
                />
                <Button
                  size="sm"
                  onClick={() => newSubtask.trim() && createSubtask.mutate(newSubtask.trim())}
                  disabled={createSubtask.isPending}
                >
                  <IconPlus size={14} />
                  Add
                </Button>
              </div>
            )}
          </div>
        </div>

        {action.source_insight_title && (
          <div className="text-small text-ink-tertiary">
            Source insight: {action.source_insight_title}
          </div>
        )}
      </div>
    </ProjectShell>
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
  const [status, setStatus] = useState<ProjectActionStatus>(subtask.status);

  useEffect(() => {
    setTitle(subtask.title);
    setStatus(subtask.status);
  }, [subtask.title, subtask.status]);

  const update = useMutation({
    mutationFn: (body: { title?: string; status?: ProjectActionStatus; percent_complete?: number }) =>
      projectActionsApi.updateSubtask(projectId, actionId, subtask.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "actions", actionId],
      });
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  const archive = useMutation({
    mutationFn: () => projectActionsApi.archiveSubtask(projectId, actionId, subtask.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "actions", actionId],
      });
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  return (
    <div className="flex items-center gap-2 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5">
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        disabled={!canEdit}
        className="min-w-0 flex-1 bg-transparent text-[13px] text-ink-primary outline-none"
      />
      {canEdit && (
        <select
          value={status}
          onChange={(e) => {
            const s = e.target.value as ProjectActionStatus;
            setStatus(s);
            update.mutate({ status: s });
          }}
          className="rounded-md border border-line-tertiary bg-bg-primary px-1.5 py-1 text-[12px] text-ink-primary"
        >
          {Object.entries(STATUS_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      )}
      {!canEdit && <span className="text-[12px] text-ink-tertiary">{STATUS_LABELS[status]}</span>}
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
