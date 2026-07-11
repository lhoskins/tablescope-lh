"use client";

import { IconRefresh } from "@tabler/icons-react";

const GRANULARITY_LABELS: Record<number, string> = {
  1: "Executive",
  2: "Strategic",
  3: "Balanced",
  4: "Detailed",
  5: "Granular",
};

export interface IntelligenceStripProps {
  running: boolean;
  lastUpdatedLabel: string | null;
  onRefresh: () => void;
  granularity: number;
  onGranularityChange: (value: number) => void;
}

export function IntelligenceStrip({
  running,
  lastUpdatedLabel,
  onRefresh,
  granularity,
  onGranularityChange,
}: IntelligenceStripProps) {
  return (
    <div className="flex items-center gap-4 rounded-lg border border-line-tertiary bg-bg-primary px-4 py-2.5">
      <div className="min-w-0 flex-1" />

      <div className="flex shrink-0 items-center gap-2 text-small text-ink-secondary">
        <label
          className="flex items-center gap-2"
          title="Slide from high-level executive insights to fine-grained, detailed analyses"
        >
          <span className="hidden sm:inline text-ink-tertiary">Depth</span>
          <input
            type="range"
            min={1}
            max={5}
            step={1}
            value={granularity}
            onChange={(e) => onGranularityChange(Number(e.target.value))}
            aria-label="Insight granularity"
            className="h-1 w-20 cursor-pointer appearance-none rounded-full bg-line-secondary accent-brand"
          />
          <span className="w-16 text-ink-primary">
            {GRANULARITY_LABELS[granularity] ?? "Balanced"}
          </span>
        </label>
      </div>

      <div className="flex shrink-0 items-center gap-3 text-small text-ink-tertiary">
        {lastUpdatedLabel && <span>{lastUpdatedLabel}</span>}
        <button
          type="button"
          onClick={onRefresh}
          aria-label="Refresh intelligence"
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 transition-colors hover:bg-bg-tertiary"
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
