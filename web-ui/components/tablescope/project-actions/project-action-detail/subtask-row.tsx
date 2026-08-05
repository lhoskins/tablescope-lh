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
} from "@/lib/api/project-actions";import { STATUS_BADGE_LABELS } from "./status-badge-labels";
import { STATUS_COLORS } from "./status-colors";
import { Avatar } from "./avatar";
import { InlineDate } from "./inline-date";



export function SubtaskRow({
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
    <div className="grid grid-cols-[1fr_120px_110px_100px_70px_44px_32px] items-center gap-2 rounded-md border border-line-tertiary bg-bg-primary px-3 py-2">
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

      <input
        type="number"
        min={1}
        max={10}
        value={subtask.effort_points ?? ""}
        disabled={!canEdit}
        onChange={(e) => update.mutate({ effort_points: e.target.value ? Number(e.target.value) : null })}
        placeholder="-"
        className="w-full rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-center text-[12px] text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
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