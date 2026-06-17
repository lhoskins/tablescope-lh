"use client";

import { useEffect } from "react";
import { IconFolderPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import {
  useBuilderStore,
  type ProjectAssignment,
} from "@/lib/stores/data-source-builder-store";
import { ProjectCard } from "./project-card";

export function RightPanel({
  className,
  tenantName,
  onReview,
  onNewProject,
}: {
  className?: string;
  tenantName: string;
  onReview: () => void;
  onNewProject: () => void;
}) {
  const { data: summaries, isLoading } = useProjectSummaries();
  const projects = useBuilderStore((s) => s.projects);
  const setProjects = useBuilderStore((s) => s.setProjects);
  const sources = useBuilderStore((s) => s.sources);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);

  // Initialise / sync project assignments from the live summaries, preserving
  // any in-session toggles, removals and scopes.
  useEffect(() => {
    if (!summaries) return;
    setProjects(
      summaries.map((p): ProjectAssignment => {
        const prev = useBuilderStore
          .getState()
          .projects.find((x) => x.projectId === p.id);
        return {
          projectId: p.id,
          projectName: p.name,
          color: p.accent ?? "#185FA5",
          isToggled: prev?.isToggled ?? false,
          existingSources: prev?.existingSources ?? [],
          sourcesToRemove: prev?.sourcesToRemove ?? [],
          scopeIds: prev?.scopeIds ?? [],
        };
      }),
    );
  }, [summaries, setProjects]);

  const pending = getPendingChanges();
  const projectsAddingTo = new Set(pending.adding.map((a) => a.projectId)).size;
  const tablesAdding = pending.adding.reduce(
    (acc, a) => acc + a.tableNames.length,
    0,
  );
  const projectsRemovingFrom = new Set(
    pending.removing.map((r) => r.projectId),
  ).size;
  const canReview = pending.adding.length > 0 || pending.removing.length > 0;

  return (
    <div className={cn("flex flex-col bg-bg-secondary", className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-2">
          <IconFolderPlus size={18} className="text-ink-secondary" />
          <h2 className="text-h3 text-ink-primary">Assign to projects</h2>
        </div>
        <Button variant="secondary" size="sm" onClick={onNewProject}>
          New project
        </Button>
      </div>

      {/* Project cards */}
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-5 pb-3">
        {isLoading && (
          <p className="py-6 text-center text-small text-ink-tertiary">
            Loading projects…
          </p>
        )}
        {!isLoading && projects.length === 0 && (
          <div className="rounded-lg border border-line-tertiary bg-bg-primary p-6 text-center">
            <p className="text-[13px] font-medium text-ink-primary">
              No projects yet
            </p>
            <Button
              variant="brandSoft"
              size="sm"
              className="mt-3"
              onClick={onNewProject}
            >
              Create your first project
            </Button>
          </div>
        )}
        {projects.map((p) => (
          <ProjectCard key={p.projectId} project={p} />
        ))}

        {/* New project card */}
        {projects.length > 0 && (
          <button
            type="button"
            onClick={onNewProject}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-line-secondary px-4 py-3 text-[13px] text-ink-secondary hover:border-brand-500 hover:text-brand-700"
          >
            <IconFolderPlus size={16} />
            Create new project with these sources
          </button>
        )}
      </div>

      {/* Summary strip */}
      <div className="border-t border-line-tertiary px-5 py-2 text-caption text-ink-secondary">
        <span className="font-medium text-brand-700">
          {tablesAdding} tables adding to {projectsAddingTo} projects
        </span>{" "}
        ·{" "}
        <span className="font-medium text-danger">
          {pending.removing.length} sources removing from {projectsRemovingFrom}{" "}
          projects
        </span>{" "}
        · Tenant: {tenantName}
      </div>

      {/* Action bar */}
      <div className="flex items-center justify-end gap-2 border-t border-line-tertiary px-5 py-3">
        <Button variant="secondary" disabled={!canReview}>
          Preview impact
        </Button>
        <Button
          variant="primary"
          disabled={!canReview || sources.length === 0}
          onClick={onReview}
        >
          Review &amp; apply changes →
        </Button>
      </div>
    </div>
  );
}
