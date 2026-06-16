"use client";

import {
  IconRefresh,
  IconSparkles,
} from "@tabler/icons-react";
import type { InsightCard } from "@/lib/api/home-intelligence";

function severityDot(severity: string): string {
  switch (severity) {
    case "critical":
      return "var(--color-danger)";
    case "urgent":
      return "var(--color-warning)";
    case "opportunity":
      return "var(--color-success)";
    default:
      return "var(--text-tertiary)";
  }
}

export interface IntelligenceStripProps {
  projectCount: number;
  insights: InsightCard[];
  running: boolean;
  lastUpdatedLabel: string | null;
  onRefresh: () => void;
}

export function IntelligenceStrip({
  projectCount,
  insights,
  running,
  lastUpdatedLabel,
  onRefresh,
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

      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto scrollbar-none">
        {insights.length === 0 && running && (
          <span className="text-small text-brand-fg/70">
            Gathering insights…
          </span>
        )}
        {insights.map((card, i) => (
          <span
            key={card.id}
            className="inline-flex shrink-0 animate-[fadeIn_300ms_ease-out_both] items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-1 text-small"
            style={{ animationDelay: `${Math.min(i, 12) * 120}ms` }}
          >
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: severityDot(card.severity) }}
            />
            <span className="max-w-[220px] truncate">{card.title}</span>
            <span className="text-brand-fg/60">· {card.projectName}</span>
          </span>
        ))}
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
