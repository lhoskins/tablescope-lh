"use client";

import { useEffect } from "react";
import { IconFolderPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import {
  useBuilderStore,
  type ProjectAssignment,
} from "@/lib/stores/data-source-builder-store";
import { ProjectCard } from "./project-card";

export function ProjectsColumn({ onNewProject }: { onNewProject: () => void }) {
  const { data: summaries, isLoading } = useProjectSummaries();
  const projects = useBuilderStore((s) => s.projects);
  const setProjects = useBuilderStore((s) => s.setProjects);

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

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-1 flex items-start justify-between px-1">
        <div>
          <h3 className="text-h3 text-ink-primary">Projects</h3>
          <p className="text-small text-ink-tertiary">
            Choose which projects receive the selected data sources
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={onNewProject}>
          New project
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-0.5 py-2">
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

        {projects.length > 0 && (
          <button
            type="button"
            onClick={onNewProject}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-line-secondary px-4 py-3 text-[13px] text-ink-secondary hover:border-brand-500 hover:text-brand-700"
          >
            <IconFolderPlus size={16} />
            Create new project with selected data sources
          </button>
        )}
      </div>
    </div>
  );
}
