"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import {
  IconArrowLeft,
  IconChevronDown,
  IconLoader2,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import {
  useProjectIntelligence,
  type ProjectIntelligenceSection,
} from "./project-intelligence-context";

interface ProjectIntelligenceHeaderProps {
  title: string;
  section: ProjectIntelligenceSection;
  actions?: ReactNode;
}

export function ProjectIntelligenceHeader({
  title,
  section,
  actions,
}: ProjectIntelligenceHeaderProps) {
  const { project, projects, isLoading, isInvalid, setProjectId } =
    useProjectIntelligence();

  return (
    <div className="mb-6 space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Link
            href={project ? `/projects/${project.id}` : "/projects"}
            title="Back to project"
            aria-label="Back to project"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-tertiary hover:bg-brand-50/60 hover:text-ink-primary"
          >
            <IconArrowLeft size={16} />
          </Link>
          <h1 className="text-2xl font-semibold text-ink-primary">{title}</h1>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="text-ink-tertiary">Project</span>
        {isLoading ? (
          <IconLoader2 size={14} className="animate-spin text-ink-tertiary" />
        ) : isInvalid ? (
          <span className="text-danger">Not accessible</span>
        ) : (
          <div className="relative">
            <select
              aria-label="Select project"
              value={project?.id ?? ""}
              onChange={(e) => {
                const id = e.target.value;
                if (id) setProjectId(id, section);
              }}
              className={cn(
                "appearance-none rounded-md border border-line-secondary bg-bg-primary py-1.5 pl-3 pr-8 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none",
                projects.length === 0 && "text-ink-tertiary",
              )}
            >
              {projects.length === 0 ? (
                <option value="">No projects available</option>
              ) : (
                projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))
              )}
            </select>
            <IconChevronDown
              size={14}
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
          </div>
        )}
      </div>
    </div>
  );
}
