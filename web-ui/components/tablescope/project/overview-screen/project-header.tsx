"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconCheck,
  IconLoader2,
  IconPencil,
  IconUsers,
  IconX,
} from "@tabler/icons-react";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { updateProject } from "@/lib/ui/use-shell-data";
import { ApiError } from "@/lib/api-client";
import { aiStatusLabel, aiStatusTone } from "@/lib/ui/format";
import type { AiStatus, ProjectSummary } from "@/lib/ui/types";

export function ProjectHeader({
  project,
  memberCount,
  aiStatus,
  onMembers,
  onToast,
}: {
  project: ProjectSummary | null;
  memberCount: number;
  aiStatus: AiStatus;
  onMembers: () => void;
  onToast: (message: string, tone?: "success" | "error" | "info") => void;
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

  return (
    <header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-line-tertiary bg-bg-primary p-4">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-lg font-semibold text-white"
          style={{ backgroundColor: project?.accent ?? "var(--brand-500)" }}
        >
          {(project?.name ?? "P").slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {editing ? (
              <div className="flex items-center gap-2">
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
                  className="h-9 rounded-md border border-line-secondary bg-bg-primary px-2 text-h1 text-ink-primary focus:border-brand-500 focus:outline-none"
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
            ) : (
              <>
                <h1 className="text-h1 text-ink-primary">
                  {project?.name ?? "Project"}
                </h1>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Rename project"
                  className="h-7 w-7 text-ink-tertiary"
                  onClick={() => setEditing(true)}
                >
                  <IconPencil size={14} />
                </Button>
              </>
            )}
            <Badge tone={statusTone} title={`Project status: ${statusLabel}`}>
              {statusLabel}
            </Badge>
          </div>
          <p className="mt-0.5 text-small text-ink-tertiary">
            {project?.visibility === "shared" ? "Shared" : "Private"} project
            {memberCount > 0 &&
              ` · ${memberCount} member${memberCount === 1 ? "" : "s"}`}
            {project?.updatedLabel && ` · Updated ${project.updatedLabel}`}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
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
    </header>
  );
}
