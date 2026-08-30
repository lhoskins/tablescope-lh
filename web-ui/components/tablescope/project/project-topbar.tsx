"use client";

import { type ReactNode, useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconCheck,
  IconLoader2,
  IconUsers,
  IconX,
} from "@tabler/icons-react";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ToastTone } from "@/components/ui/toast";
import { updateProject } from "@/lib/ui/use-shell-data";
import { ApiError } from "@/lib/api-client";
import { aiStatusLabel, aiStatusTone } from "@/lib/ui/format";
import type { AiStatus, ProjectSummary } from "@/lib/ui/types";

/**
 * Left side of the project top bar: `<project name> › <screen>` plus the
 * project's AI status. Every project screen shows the same thing, only the
 * screen segment changes -- that's what makes the chrome identical whichever
 * nav card you're on. The name stays click-to-rename, the inline edit that
 * used to live on the in-page project header card.
 */
export function ProjectTitleBreadcrumb({
  project,
  screenLabel,
  aiStatus,
  onToast,
}: {
  project: ProjectSummary | null;
  screenLabel?: string;
  aiStatus: AiStatus;
  onToast: (message: string, tone?: ToastTone) => void;
}) {
  const statusLabel = aiStatusLabel(aiStatus);
  const statusTone = aiStatusTone(aiStatus);

  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(project?.name ?? "");

  useEffect(() => {
    setValue(project?.name ?? "");
  }, [project?.name]);

  const mutation = useMutation({
    mutationFn: (name: string) =>
      updateProject(String(project?.id ?? ""), { name: name.trim() }),
    onSuccess: () => {
      onToast("Project renamed.", "success");
      void queryClient.invalidateQueries({
        queryKey: ["projects", "summaries", false, 0],
      });
      setEditing(false);
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.status === 403) {
        onToast(
          "Only the project owner or an admin can rename this project.",
          "error",
        );
      } else {
        onToast("Could not rename project. Please try again.", "error");
      }
    },
  });

  const canSave =
    value.trim().length > 0 && value.trim() !== (project?.name ?? "");

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (canSave) mutation.mutate(value.trim());
    } else if (event.key === "Escape") {
      event.preventDefault();
      setEditing(false);
      setValue(project?.name ?? "");
    }
  };

  if (editing) {
    return (
      <div className="flex min-w-0 items-center gap-2">
        <input
          autoFocus
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={() => {
            setEditing(false);
            setValue(project?.name ?? "");
          }}
          disabled={mutation.isPending}
          className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-[15px] font-semibold text-ink-primary focus:border-brand-500 focus:outline-none"
          aria-label="Project name"
        />
        <Button
          variant="secondary"
          size="sm"
          disabled={!canSave || mutation.isPending}
          onClick={() => mutation.mutate(value.trim())}
        >
          {mutation.isPending ? (
            <IconLoader2 size={14} className="animate-spin" />
          ) : (
            <IconCheck size={14} />
          )}
          Save
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={mutation.isPending}
          onClick={() => {
            setEditing(false);
            setValue(project?.name ?? "");
          }}
        >
          <IconX size={14} />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 items-center gap-2">
      <button
        type="button"
        onClick={() => setEditing(true)}
        title="Click to rename"
        className="-mx-1 max-w-[240px] truncate rounded px-1 text-left text-[15px] font-semibold text-ink-primary hover:bg-bg-secondary"
      >
        {project?.name ?? "Project"}
      </button>
      {screenLabel && (
        <>
          <span aria-hidden className="text-ink-tertiary">
            ›
          </span>
          <span className="truncate text-[13px] text-ink-secondary">
            {screenLabel}
          </span>
        </>
      )}
      <Badge tone={statusTone} title={`Project status: ${statusLabel}`}>
        {statusLabel}
      </Badge>
    </div>
  );
}

/**
 * Right side of the project top bar: whatever actions the current screen
 * contributes, then the two project-wide controls (Private/Shared and
 * Members) that sit in the same place on every screen.
 */
export function ProjectTopBarControls({
  project,
  actions,
  onMembers,
  onToast,
}: {
  project: ProjectSummary | null;
  actions?: ReactNode;
  onMembers: () => void;
  onToast: (message: string, tone?: ToastTone) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {actions}
      <ShareToggle
        projectId={String(project?.id ?? "")}
        shared={project?.visibility === "shared"}
        onToast={onToast}
      />
      <Button variant="secondary" onClick={onMembers}>
        <IconUsers size={14} />
        Members
      </Button>
    </div>
  );
}
