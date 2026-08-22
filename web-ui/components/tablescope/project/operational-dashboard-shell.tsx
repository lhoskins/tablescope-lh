"use client";

import type { ReactNode } from "react";
import { IconArrowLeft } from "@tabler/icons-react";
import { cn } from "@/lib/cn";

export type OperationalStoryTone = "critical" | "warning" | "positive" | "neutral";

export interface OperationalStory {
  id: string;
  title: string;
  detail: string;
  tone?: OperationalStoryTone;
  onClick?: () => void;
}

/** One "Operational Brief" bullet as persisted in `config.operationalWidgets`. */
export interface OperationalNarrativeItem {
  label?: string;
  detail?: string;
  tone?: OperationalStoryTone;
}

const BRIEF_DEFAULTS: Array<{ title: string; tone: OperationalStoryTone }> = [
  { title: "Backing risk", tone: "critical" },
  { title: "Primary driver", tone: "warning" },
  { title: "Recommended action", tone: "positive" },
];

/**
 * Normalize a brief widget's items into the three stories the strip renders.
 *
 * Accepts both shapes on purpose: the designer now emits structured
 * `{label, detail, tone}` items, but dashboards saved before that still hold
 * plain strings, and those must keep rendering (rather than crashing React
 * with an object child) without a migration.
 */
export function toOperationalStories(
  items: Array<string | OperationalNarrativeItem> | undefined,
  summary?: string,
): OperationalStory[] {
  const list = items ?? [];
  return BRIEF_DEFAULTS.map((fallback, index) => {
    const item = list[index];
    const structured = typeof item === "object" && item !== null ? item : undefined;
    return {
      id: `operational-story-${index}`,
      title: structured?.label || fallback.title,
      detail:
        (typeof item === "string" ? item : structured?.detail) ||
        (index === 0 ? summary : undefined) ||
        "AI will refresh this story from governed project data.",
      tone: structured?.tone || fallback.tone,
    };
  });
}

function toneClass(tone: OperationalStoryTone | undefined): string {
  if (tone === "critical") return "bg-rose-500";
  if (tone === "warning") return "bg-amber-500";
  if (tone === "positive") return "bg-emerald-500";
  return "bg-blue-500";
}

/**
 * Shared title/control row for both governed ITSM dashboards and AI-created
 * Operational Insight dashboards. Keeping this shell shared prevents the two
 * dashboard families from drifting apart again.
 */
export function OperationalDashboardHeader({
  title,
  subtitle,
  live = false,
  onBack,
  controls,
}: {
  title: string;
  subtitle: string;
  live?: boolean;
  onBack: () => void;
  controls: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div className="flex min-w-0 items-start gap-2">
        <button
          type="button"
          onClick={onBack}
          aria-label="Back to dashboards"
          className="mt-1 rounded-md p-1 text-ink-tertiary hover:bg-brand-50/60 hover:text-ink-primary"
        >
          <IconArrowLeft size={18} />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-h2 text-ink-primary">{title}</h1>
            {live && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">Live</span>}
          </div>
          <p className="truncate text-xs text-ink-tertiary">{subtitle}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">{controls}</div>
    </div>
  );
}

/** The full-width story strip used immediately beneath the shared header. */
export function OperationalBriefStrip({
  stories,
  title = "Operational brief",
  subtitle = "The story behind the selected period",
}: {
  stories: OperationalStory[];
  title?: string;
  subtitle?: string;
}) {
  if (stories.length === 0) return null;
  return (
    <section className="grid items-center gap-4 border-y border-line-tertiary px-1 py-3 md:grid-cols-[minmax(150px,0.6fr)_minmax(0,2.4fr)]" aria-label={title}>
      <div>
        <div className="text-sm font-semibold text-ink-primary">{title}</div>
        <div className="text-[11px] text-ink-tertiary">{subtitle}</div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {stories.slice(0, 3).map((story) => {
          const content = (
            <>
              <span className={cn("mt-1.5 h-2.5 w-2.5 rounded-full", toneClass(story.tone))} />
              <span>
                <span className="block text-xs font-semibold text-ink-primary">{story.title}</span>
                <span className="block text-[11px] leading-4 text-ink-tertiary">{story.detail}</span>
              </span>
            </>
          );
          return story.onClick ? (
            <button type="button" key={story.id} className="grid grid-cols-[auto_1fr] gap-2 text-left" onClick={story.onClick}>{content}</button>
          ) : (
            <div key={story.id} className="grid grid-cols-[auto_1fr] gap-2 text-left">{content}</div>
          );
        })}
      </div>
    </section>
  );
}
