"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { IconFilter, IconRefresh, IconSparkles, IconTrash } from "@tabler/icons-react";
import { DepthControl } from "@/components/tablescope/insights/depth-control";

export interface FilterableProject {
  id: string;
  name: string;
  accent?: string;
}

export interface IntelligenceStripProps {
  scope?: "business" | "project";
  projectCount?: number;
  /** Total accessible projects; when provided, a subset is rendered as "Showing X of Y". */
  totalProjectCount?: number;
  running: boolean;
  lastUpdatedLabel: string | null;
  onRefresh: () => void;
  onClearCache?: () => void;
  isClearingCache?: boolean;
  granularity: number;
  onGranularityChange: (value: number) => void;
  availableProjects: FilterableProject[];
  selectedProjectIds: Set<string>;
  onToggleProject: (id: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
}

function ProjectFilter({
  availableProjects,
  selectedProjectIds,
  onToggleProject,
  onSelectAll,
  onClear,
}: {
  availableProjects: FilterableProject[];
  selectedProjectIds: Set<string>;
  onToggleProject: (id: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const selectedCount = selectedProjectIds.size;
  const allSelected =
    availableProjects.length > 0 &&
    availableProjects.every((p) => selectedProjectIds.has(p.id));

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label="Filter by project"
          title="Filter by project"
          className="inline-flex items-center gap-1.5 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-small font-medium text-ink-secondary transition-colors hover:bg-bg-tertiary"
        >
          <IconFilter size={16} />
          <span className="hidden sm:inline">
            {allSelected ? "All projects" : `${selectedCount} project${selectedCount === 1 ? "" : "s"}`}
          </span>
          {!allSelected && selectedCount > 0 && (
            <span className="rounded-full bg-bg-tertiary px-1.5 py-0 text-[11px] text-ink-secondary">
              {selectedCount}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-72 rounded-lg border border-line-secondary bg-bg-primary p-3 shadow-lg"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-small font-medium text-ink-primary">
              Filter by project
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onSelectAll}
                className="text-xs font-medium text-brand hover:underline"
              >
                Select all
              </button>
              <button
                type="button"
                onClick={onClear}
                className="text-xs font-medium text-brand hover:underline"
              >
                Clear
              </button>
            </div>
          </div>
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {availableProjects.length === 0 && (
              <p className="py-2 text-[13px] text-ink-tertiary">
                No projects available.
              </p>
            )}
            {availableProjects.map((p) => {
              const checked = selectedProjectIds.has(p.id);
              return (
                <label
                  key={p.id}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1.5 hover:bg-bg-secondary"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleProject(p.id)}
                    className="h-4 w-4 rounded border-line-secondary accent-brand"
                  />
                  <span
                    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: p.accent ?? "#5c5a55" }}
                  />
                  <span className="flex-1 truncate text-[13px] text-ink-primary">
                    {p.name}
                  </span>
                </label>
              );
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function IntelligenceStrip({
  scope = "business",
  projectCount = 0,
  totalProjectCount,
  running,
  lastUpdatedLabel,
  onRefresh,
  onClearCache,
  isClearingCache,
  granularity,
  onGranularityChange,
  availableProjects,
  selectedProjectIds,
  onToggleProject,
  onSelectAll,
  onClear,
}: IntelligenceStripProps) {
  const isProject = scope === "project";
  const isFiltered =
    !isProject &&
    totalProjectCount != null &&
    totalProjectCount > 0 &&
    projectCount < totalProjectCount;

  const toolbarLabel = isProject ? "Project Insights toolbar" : "Business Insights toolbar";
  const clearCacheLabel = isProject
    ? "Clear Project Insight cache"
    : "Clear Business Insight cache";
  const refreshLabel = isProject ? "Refresh project insights" : "Refresh intelligence";

  const runningText = isProject
    ? "Analyzing this project…"
    : `Analyzing ${projectCount} project${projectCount === 1 ? "" : "s"}…`;

  return (
    <div
      className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
      aria-label={toolbarLabel}
    >
      <div className="flex flex-wrap items-center gap-3">
        {!isProject && (
          <ProjectFilter
            availableProjects={availableProjects}
            selectedProjectIds={selectedProjectIds}
            onToggleProject={onToggleProject}
            onSelectAll={onSelectAll}
            onClear={onClear}
          />
        )}
        {isFiltered && (
          <span className="text-small text-ink-tertiary">
            {projectCount} of {totalProjectCount} projects
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-start gap-3 sm:justify-end">
        {running && (
          <span
            className="inline-flex items-center gap-1.5 text-small text-ink-tertiary"
            aria-live="polite"
          >
            <IconSparkles size={16} className="animate-pulse" aria-hidden />
            {runningText}
          </span>
        )}

        <label
          className="flex items-center gap-2 text-small text-ink-secondary"
          title="Slide from high-level executive insights to fine-grained, detailed analyses"
        >
          <span className="hidden sm:inline">Depth</span>
          <DepthControl
            value={granularity}
            onChange={onGranularityChange}
          />
        </label>

        {lastUpdatedLabel && (
          <span className="text-small text-ink-tertiary">{lastUpdatedLabel}</span>
        )}

        {onClearCache && (
          <button
            type="button"
            onClick={onClearCache}
            disabled={isClearingCache}
            title={clearCacheLabel}
            aria-label={clearCacheLabel}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ink-secondary transition-colors hover:bg-bg-tertiary disabled:opacity-50"
          >
            <IconTrash size={15} />
          </button>
        )}

        <button
          type="button"
          onClick={onRefresh}
          aria-label={refreshLabel}
          title={refreshLabel}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ink-secondary transition-colors hover:bg-bg-tertiary"
        >
          <IconRefresh
            size={15}
            className={running ? "animate-spin" : undefined}
          />
        </button>
      </div>
    </div>
  );
}
