"use client";

import {
  IconRefresh,
  IconSparkles,
} from "@tabler/icons-react";

const GRANULARITY_LABELS: Record<number, string> = {
  1: "Executive",
  2: "Strategic",
  3: "Balanced",
  4: "Detailed",
  5: "Granular",
};

export interface IntelligenceStripProps {
  projectCount: number;
  running: boolean;
  lastUpdatedLabel: string | null;
  onRefresh: () => void;
  granularity: number;
  onGranularityChange: (value: number) => void;
  /** Cross-project synthesis headline, folded into the band across the width. */
  synthesisHeadline: string | null;
}

export function IntelligenceStrip({
  projectCount,
  running,
  lastUpdatedLabel,
  onRefresh,
  granularity,
  onGranularityChange,
  synthesisHeadline,
}: IntelligenceStripProps) {
  return (
    <div className="flex items-center gap-4 rounded-lg bg-brand px-4 py-2.5 text-brand-fg">
      <div className="flex shrink-0 items-center gap-2 text-small font-medium">
        <IconSparkles
          size={16}
          className={running ? "animate-pulse" : undefined}
        />
        <span>
          {running ? "AI running across" : "AI analyzed"} {projectCount} project
          {projectCount === 1 ? "" : "s"}
        </span>
      </div>

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
