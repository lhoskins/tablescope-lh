"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import {
  IconFilter,
  IconRefresh,
  IconSparkles,
} from "@tabler/icons-react";

export interface FilterableProject {
  id: string;
  name: string;
  accent?: string;
}

const GRANULARITY_LABELS: Record<number, string> = {
  1: "Executive",
  2: "Strategic",
  3: "Balanced",
  4: "Detailed",
  5: "Granular",
};

export interface IntelligenceStripProps {
  projectCount: number;
  /** Total accessible projects; when provided, a subset is rendered as "Showing X of Y". */
  totalProjectCount?: number;
  running: boolean;
  lastUpdatedLabel: string | null;
  onRefresh: () => void;
  granularity: number;
  onGranularityChange: (value: number) => void;
  /** Cross-project synthesis headline, folded into the band across the width. */
  synthesisHeadline: string | null;
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
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-small font-medium text-brand-fg transition-colors hover:bg-white/15"
        >
          <IconFilter size={16} />
          <span className="hidden sm:inline">
            {allSelected ? "All projects" : `${selectedCount} project${selectedCount === 1 ? "" : "s"}`}
          </span>
          {!allSelected && selectedCount > 0 && (
            <span className="rounded-full bg-white/20 px-1.5 py-0 text-[11px]">
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
  projectCount,
  totalProjectCount,
  running,
  lastUpdatedLabel,
  onRefresh,
  granularity,
  onGranularityChange,
  synthesisHeadline,
  availableProjects,
  selectedProjectIds,
  onToggleProject,
  onSelectAll,
  onClear,
}: IntelligenceStripProps) {
  const isFiltered =
    totalProjectCount != null && totalProjectCount > 0 && projectCount < totalProjectCount;

  return (
    <div className="flex items-center gap-4 rounded-lg bg-brand px-4 py-2.5 text-brand-fg">
      <div className="flex shrink-0 items-center gap-2 text-small font-medium">
        <IconSparkles
          size={16}
          className={running ? "animate-pulse" : undefined}
        />
        <span>
          {isFiltered
            ? "Showing"
            : running
              ? "AI running across"
              : "AI analyzed"}{" "}
          {projectCount} project{projectCount === 1 ? "" : "s"}
          {isFiltered && ` of ${totalProjectCount}`}
        </span>
      </div>

      <ProjectFilter
        availableProjects={availableProjects}
        selectedProjectIds={selectedProjectIds}
        onToggleProject={onToggleProject}
        onSelectAll={onSelectAll}
        onClear={onClear}
      />

      <div className="min-w-0 flex-1">
        {synthesisHeadline ? (
          <span className="block truncate text-small font-medium text-brand-fg">
            {synthesisHeadline}
          </span>
        ) : running ? (
          <span className="text-small text-brand-fg/70">
            Gathering insights…
          </span>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-2 text-small text-brand-fg/90">
        <label
          className="flex items-center gap-2"
          title="Slide from high-level executive insights to fine-grained, detailed analyses"
        >
          <span className="hidden sm:inline text-brand-fg/70">Depth</span>
          <input
            type="range"
            min={1}
            max={5}
            step={1}
            value={granularity}
            onChange={(e) => onGranularityChange(Number(e.target.value))}
            aria-label="Insight granularity"
            className="h-1 w-20 cursor-pointer appearance-none rounded-full bg-white/30 accent-white"
          />
          <span className="w-16 text-brand-fg">
            {GRANULARITY_LABELS[granularity] ?? "Balanced"}
          </span>
        </label>
      </div>

      <div className="flex shrink-0 items-center gap-3 text-small text-brand-fg/80">
        {lastUpdatedLabel && <span>{lastUpdatedLabel}</span>}
        <button
          type="button"
          onClick={onRefresh}
          aria-label="Refresh intelligence"
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 transition-colors hover:bg-white/15"
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
