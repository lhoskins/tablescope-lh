"use client";

import { useCallback, useState } from "react";
import {
  IconChartHistogram,
  IconLayoutDashboard,
  IconBulb,
  IconCheck,
  IconLoader2,
  IconDeviceFloppy,
  IconPlayerPlay,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import {
  suggestQueries,
  suggestDashboards,
  suggestInsights,
  saveDashboardSuggestion,
  type QuerySuggestionsProject,
  type DashboardSuggestionsProject,
  type ProjectResult,
} from "@/lib/api/home-intelligence";
import {
  IntelligenceCard,
  InsightChartBlock,
} from "@/components/tablescope/home/intelligence-card";
import { QuerySuggestionPreviewModal } from "@/components/tablescope/home/query-suggestion-preview-modal";

type Pill = "queries" | "dashboards" | "insights";

const PILLS: { key: Pill; label: string; icon: typeof IconBulb }[] = [
  { key: "queries", label: "New Query Suggestions", icon: IconChartHistogram },
  {
    key: "dashboards",
    label: "New Dashboard Suggestions",
    icon: IconLayoutDashboard,
  },
  { key: "insights", label: "Insights & Opportunities", icon: IconBulb },
];

export function HomeAiSuggestions() {
  const [active, setActive] = useState<Pill | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [queryProjects, setQueryProjects] = useState<
    QuerySuggestionsProject[] | null
  >(null);
  const [dashboardProjects, setDashboardProjects] = useState<
    DashboardSuggestionsProject[] | null
  >(null);
  const [insightProjects, setInsightProjects] = useState<
    ProjectResult[] | null
  >(null);

  const run = useCallback(async (pill: Pill) => {
    setActive(pill);
    setError(null);
    setLoading(true);
    try {
      if (pill === "queries") {
        const res = await suggestQueries();
        setQueryProjects(res.projects);
      } else if (pill === "dashboards") {
        const res = await suggestDashboards();
        setDashboardProjects(res.projects);
      } else {
        const res = await suggestInsights();
        setInsightProjects(res.projects);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suggestion failed");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="mt-4">
      <div className="flex flex-wrap justify-center gap-2">
        {PILLS.map((p) => {
          const Icon = p.icon;
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => void run(p.key)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                active === p.key
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-line-secondary bg-bg-primary text-ink-secondary hover:border-brand-100 hover:text-brand-700",
              )}
            >
              <Icon size={15} />
              {p.label}
            </button>
          );
        })}
      </div>

      {active && (
        <div className="mx-auto mt-6 w-full max-w-content">
          {loading && (
            <div className="flex items-center justify-center gap-2 rounded-lg border border-line-tertiary bg-bg-primary py-10 text-small text-ink-tertiary">
              <IconLoader2 size={16} className="animate-spin" />
              Generating across your projects…
            </div>
          )}
          {!loading && error && (
            <div className="rounded-lg border border-danger/30 bg-danger/5 p-4 text-small text-danger">
              {error}
            </div>
          )}
          {!loading && !error && active === "queries" && (
            <QuerySuggestionsPanel projects={queryProjects ?? []} />
          )}
          {!loading && !error && active === "dashboards" && (
            <DashboardSuggestionsPanel projects={dashboardProjects ?? []} />
          )}
          {!loading && !error && active === "insights" && (
            <InsightsPanel projects={insightProjects ?? []} />
          )}
        </div>
      )}
    </div>
  );
}

function ProjectHeader({
  name,
  color,
}: {
  name: string;
  color: string;
}) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: color }}
      />
      <h3 className="text-h3 text-ink-primary">{name}</h3>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary py-10 text-center text-small text-ink-tertiary">
      {label}
    </div>
  );
}

// ── Queries ──────────────────────────────────────────────────────────

function QuerySuggestionsPanel({
  projects,
}: {
  projects: QuerySuggestionsProject[];
}) {
  const withResults = projects.filter((p) => p.suggestions.length > 0);
  if (withResults.length === 0) {
    return (
      <EmptyState label="No query suggestions for your projects right now." />
    );
  }
  return (
    <div className="space-y-8">
      {withResults.map((p) => (
        <section key={p.projectId}>
          <ProjectHeader name={p.projectName} color={p.projectColor} />
          <div className="space-y-3">
            {p.suggestions.map((s, i) => (
              <QuerySuggestionCard
                key={i}
                projectId={Number(p.projectId)}
                title={s.title}
                description={s.description}
                sql={s.sql}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function QuerySuggestionCard({
  projectId,
  title,
  description,
  sql,
}: {
  projectId: number;
  title: string;
  description: string;
  sql: string;
}) {
  const [preview, setPreview] = useState(false);
  const [saved, setSaved] = useState(false);

  return (
    <article className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-body font-medium text-ink-primary">{title}</h4>
          {description && (
            <p className="mt-0.5 text-small text-ink-secondary">{description}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setPreview(true)}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-small font-medium transition-colors",
            saved
              ? "border-success/40 bg-success/10 text-success"
              : "border-line-secondary text-ink-secondary hover:border-brand-100 hover:text-brand-700",
          )}
        >
          {saved ? (
            <>
              <IconCheck size={14} /> Saved
            </>
          ) : (
            <>
              <IconPlayerPlay size={14} /> Preview
            </>
          )}
        </button>
      </header>
      <pre className="mt-3 overflow-x-auto rounded-md bg-bg-secondary p-3 text-caption text-ink-secondary">
        <code>{sql}</code>
      </pre>
      <QuerySuggestionPreviewModal
        open={preview}
        projectId={projectId}
        title={title}
        description={description}
        sql={sql}
        onClose={() => setPreview(false)}
        onSaved={() => setSaved(true)}
      />
    </article>
  );
}

// ── Dashboards ───────────────────────────────────────────────────────

function DashboardSuggestionsPanel({
  projects,
}: {
  projects: DashboardSuggestionsProject[];
}) {
  const withResults = projects.filter(
    (p) => p.dashboard && p.dashboard.widgets.length > 0,
  );
  if (withResults.length === 0) {
    return (
      <EmptyState label="No dashboard suggestions for your projects right now." />
    );
  }
  return (
    <div className="space-y-8">
      {withResults.map((p) => (
        <DashboardSuggestionCard
          key={p.projectId}
          project={p}
        />
      ))}
    </div>
  );
}

function DashboardSuggestionCard({
  project,
}: {
  project: DashboardSuggestionsProject;
}) {
  const dashboard = project.dashboard!;
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setState("saving");
    setErr(null);
    try {
      await saveDashboardSuggestion({
        project_id: Number(project.projectId),
        title: dashboard.title,
        widgets: dashboard.widgets.map((w) => ({
          title: w.title,
          sql: w.sql,
          chartType: w.chartType,
          labelColumn: w.labelColumn,
          valueColumn: w.valueColumn,
        })),
      });
      setState("saved");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
      setState("idle");
    }
  };

  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <ProjectHeader name={project.projectName} color={project.projectColor} />
          <p className="text-small text-ink-secondary">{dashboard.title}</p>
        </div>
        <button
          type="button"
          onClick={() => void save()}
          disabled={state !== "idle"}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-small font-medium transition-colors",
            state === "saved"
              ? "border-success/40 bg-success/10 text-success"
              : "border-line-secondary text-ink-secondary hover:border-brand-100 hover:text-brand-700 disabled:opacity-50",
          )}
        >
          {state === "saved" ? (
            <>
              <IconCheck size={14} /> Saved
            </>
          ) : state === "saving" ? (
            <>
              <IconLoader2 size={14} className="animate-spin" /> Saving…
            </>
          ) : (
            <>
              <IconDeviceFloppy size={14} /> Save dashboard
            </>
          )}
        </button>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {dashboard.widgets.map((w, i) => (
          <div
            key={i}
            className="rounded-md border border-line-tertiary bg-bg-secondary/40 p-3"
          >
            <div className="mb-2 text-small font-medium text-ink-primary">
              {w.title}
            </div>
            <InsightChartBlock chart={w.chart} />
          </div>
        ))}
      </div>
      {err && <p className="mt-2 text-small text-danger">{err}</p>}
    </section>
  );
}

// ── Insights ─────────────────────────────────────────────────────────

function InsightsPanel({ projects }: { projects: ProjectResult[] }) {
  const withResults = projects.filter((p) => p.insights.length > 0);
  if (withResults.length === 0) {
    return (
      <EmptyState label="No insights for your projects right now." />
    );
  }
  return (
    <div className="space-y-8">
      {withResults.map((p) => (
        <section key={p.projectId}>
          <ProjectHeader name={p.projectName} color={p.projectColor} />
          <div className="space-y-3">
            {p.insights.map((card) => (
              <IntelligenceCard key={card.id} card={card} hideActions />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
