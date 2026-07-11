"use client";

import { useRouter } from "next/navigation";
import {
  IconChartBar,
  IconCircleCheck,
  IconLoader2,
  IconReportAnalytics,
} from "@tabler/icons-react";
import type {
  InsightCard,
  IntelligenceSettings,
  ProjectResult,
  StreamProject,
} from "@/lib/api/home-intelligence";

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 py-1.5">
      <span className="text-small text-ink-secondary">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-brand" : "bg-line-secondary"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "left-0.5 translate-x-4" : "left-0.5"
          }`}
        />
      </button>
    </label>
  );
}

function Panel({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-caption uppercase tracking-wide text-ink-tertiary">
          {title}
        </h3>
        {badge}
      </div>
      {children}
    </section>
  );
}

export interface IntelligenceSidebarProps {
  projects: StreamProject[];
  results: Record<string, ProjectResult>;
  completed: Set<string>;
  refreshing?: boolean;
  freshCompleted?: Set<string>;
  insights: InsightCard[];
  cardsInReport: number;
  settings: IntelligenceSettings | null;
  onStartReport: () => void;
  onToggleSetting: (key: keyof IntelligenceSettings, value: boolean) => void;
}

export function IntelligenceSidebar({
  projects,
  results,
  completed,
  refreshing = false,
  freshCompleted,
  insights,
  cardsInReport,
  settings,
  onStartReport,
  onToggleSetting,
}: IntelligenceSidebarProps) {
  const router = useRouter();
  const queryLog = [...insights].slice(-8).reverse();

  return (
    <aside className="w-[320px] shrink-0 space-y-4">
      {/* Report builder CTA */}
      <section className="rounded-lg border border-brand/30 bg-ai-bg p-4">
        <div className="flex items-center gap-2 text-ai">
          <IconReportAnalytics size={18} />
          <h3 className="text-h3">Live Report Builder</h3>
        </div>
        <p className="mt-1 text-small text-ink-secondary">
          Assemble insights into a shareable live report. Viewers re-run the
          queries with their own access.
        </p>
        <button
          type="button"
          onClick={onStartReport}
          className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-brand px-3 py-2 text-small font-medium text-brand-fg transition-opacity hover:opacity-90"
        >
          <IconChartBar size={15} />
          Start report
          {cardsInReport > 0 && (
            <span className="ml-1 rounded-full bg-white/25 px-1.5 text-caption">
              {cardsInReport}
            </span>
          )}
        </button>
      </section>

      {/* Projects at a glance */}
      <Panel title="Projects at a glance">
        <ul className="space-y-2">
          {projects.length === 0 && (
            <li className="text-small text-ink-tertiary">No projects yet.</li>
          )}
          {projects.map((p) => {
            const result = results[p.id];
            const done = refreshing
              ? (freshCompleted?.has(p.id) ?? false)
              : completed.has(p.id);
            const count = result?.insights.length ?? 0;
            return (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => router.push(`/projects/${p.id}`)}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-bg-tertiary"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: p.color }}
                    />
                    <span className="truncate text-small text-ink-primary">
                      {p.name}
                    </span>
                  </span>
                  {done ? (
                    <span className="shrink-0 text-caption text-ink-tertiary">
                      {count} insight{count === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="inline-flex shrink-0 items-center gap-1 text-caption text-ink-tertiary">
                      <IconLoader2 size={12} className="animate-spin" />
                      Analyzing
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </Panel>

      {/* AI query log */}
      <Panel
        title="AI query log"
        badge={
          <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-caption font-medium text-success">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            Live
          </span>
        }
      >
        <ul className="space-y-1.5">
          {queryLog.length === 0 && (
            <li className="text-small text-ink-tertiary">
              Queries will appear here as they run.
            </li>
          )}
          {queryLog.map((card) => (
            <li
              key={card.id}
              className="flex animate-[slideInRight_300ms_ease-out_both] items-start gap-2"
            >
              <IconCircleCheck
                size={14}
                className="mt-0.5 shrink-0 text-success"
              />
              <div className="min-w-0">
                <div className="truncate text-small text-ink-primary">
                  {card.insightType}
                </div>
                <div className="truncate text-caption text-ink-tertiary">
                  {card.projectName} ·{" "}
                  {card.sources.tables[0] ??
                    card.sources.documents[0] ??
                    "documents"}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      {/* Intelligence settings */}
      <Panel title="Intelligence settings">
        {settings ? (
          <div className="divide-y divide-line-tertiary">
            <Toggle
              label="Run on home load"
              checked={settings.run_on_load}
              onChange={(v) => onToggleSetting("run_on_load", v)}
            />
            <Toggle
              label="Cross-project synthesis"
              checked={settings.cross_project}
              onChange={(v) => onToggleSetting("cross_project", v)}
            />
            <Toggle
              label="Email digest"
              checked={settings.email_digest}
              onChange={(v) => onToggleSetting("email_digest", v)}
            />
          </div>
        ) : (
          <div className="text-small text-ink-tertiary">Loading settings…</div>
        )}
      </Panel>
    </aside>
  );
}
