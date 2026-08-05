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
} from "@/lib/api/project-actions";import { STATUS_BADGE_LABELS } from "./project-action-detail/status-badge-labels";
import { PRIORITY_LABELS } from "./project-action-detail/priority-labels";
import { inputToDate } from "./project-action-detail/input-to-date";
import { LabeledSelect } from "./project-action-detail/labeled-select";
import { LabeledDate } from "./project-action-detail/labeled-date";
import { SubtaskRow } from "./project-action-detail/subtask-row";



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
