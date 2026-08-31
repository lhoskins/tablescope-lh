"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconArrowUpRight,
  IconBriefcase,
  IconCalendarDue,
  IconChartLine,
  IconCircleCheck,
  IconFileText,
  IconSettings2,
  IconSparkles,
  IconTargetArrow,
} from "@tabler/icons-react";
import { buildMultiDimWidget } from "@/components/tablescope/home/intelligence-card/build-multi-dim-widget";
import { autoValueScale } from "@/components/dashboard/EChartsWidget/format-number";
import { Button } from "@/components/ui/button";
import {
  OperationalChart,
  toOperationalChartData,
  type OperationalChartData,
} from "@/components/dashboard/OperationalInsightGrid";
import type { WidgetConfig, WidgetType } from "@/components/dashboard/types";
import { getHomeActionSummary, type HomeActionItem } from "@/lib/api/home-actions";
import {
  getIntelligenceSnapshot,
  getPreferences,
  updatePreferences,
} from "@/lib/api/home-intelligence";
import type { InsightChart } from "@/lib/api/home-intelligence";
import { useAllDocuments } from "@/lib/ui/use-shell-data";
import {
  buildHomeDevelopments,
  homePersonaProfile,
  normalizeHomePersona,
  rankHomeInsights,
  selectPerformanceInsight,
} from "./home-persona";
import { HomeSettingsDialog } from "./home-settings-dialog";

/**
 * Company performance renders through the same ITSM chart renderer the
 * ITSM preset dashboards use (skinny horizontal bars, the subtle 10%-opacity
 * line-area fill) instead of the generic WidgetRenderer/EChartsWidget engine
 * InsightChartView uses everywhere else -- so this one card matches the ITSM
 * visual language the rest of the Home briefing was built to, rather than
 * looking like a plain Business Insight card. Reuses the same two building
 * blocks InsightChartView itself uses (buildMultiDimWidget for a tabular
 * chart, or a synthetic single-series widget) so any chart type Home might
 * rank to the top still renders -- just through the ITSM-styled path.
 */
function toItsmPerformanceChart(chart: InsightChart): OperationalChartData | null {
  const dataRows = chart.data.rows;
  if (dataRows && dataRows.length > 0) {
    return toOperationalChartData(buildMultiDimWidget(chart, dataRows), dataRows);
  }

  const series = chart.data.series;
  if (!series || series.length === 0) return null;
  const valueName = chart.seriesLabels?.value ?? chart.roles?.y ?? "value";
  const xName = chart.roles?.x ?? "label";
  const rows = series.map((item) => ({ [xName]: item.label, [valueName]: item.value }));
  const widget: WidgetConfig = {
    id: "company-performance",
    type: chart.type as WidgetType,
    chartSubtype: (chart.subtype || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: xName,
    xColumnType: "string",
    yColumn: valueName,
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    // Without this, ItsmChart deliberately renders unformatted (see its own
    // comment) -- that's meant for ITSM presets, not this AI-ranked chart,
    // so give it the same shared K/M axis unit buildMultiDimWidget's rows
    // path already gets.
    visualizationOptions: { valueScale: autoValueScale(series.map((item) => item.value)) },
    colSpan: 1,
    position: 0,
  };
  return toOperationalChartData(widget, rows);
}

const DEFAULT_FOCUS = [
  "Revenue vs backlog",
  "ITSM SLA risk",
  "Actions due this week",
];

const RISK_SEVERITIES = new Set(["critical", "urgent", "warning", "watch"]);
const OPPORTUNITY_SEVERITIES = new Set(["opportunity", "recommendation"]);

function dueLabel(value: string | null): { text: string; overdue: boolean } {
  if (!value) return { text: "No due date", overdue: false };
  const due = new Date(value);
  const today = new Date();
  const days = Math.ceil((due.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return { text: `${Math.abs(days)}d overdue`, overdue: true };
  if (days === 0) return { text: "Due today", overdue: false };
  if (days === 1) return { text: "Due tomorrow", overdue: false };
  return {
    text: `Due ${due.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    })}`,
    overdue: false,
  };
}

function assignedSummary(actions: HomeActionItem[]): string {
  if (!actions.length) return "No active actions are assigned to you.";
  const overdue = actions.filter((action) => dueLabel(action.due_date).overdue).length;
  if (overdue) return `${overdue} overdue action${overdue === 1 ? "" : "s"} require your response.`;
  return `${actions.length} active action${actions.length === 1 ? "" : "s"} are waiting for your response.`;
}

function truncate(value: string, length = 145): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > length
    ? `${normalized.slice(0, length).trimEnd()}…`
    : normalized;
}

export function PersonalizedHome({
  projectCount,
  greetingText,
  onPersonalize,
}: {
  projectCount: number;
  greetingText: string;
  onPersonalize?: (handler: () => void) => void;
}) {
  const queryClient = useQueryClient();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { data: actionSummary, isLoading: actionsLoading } = useQuery({
    queryKey: ["home-action-summary"],
    queryFn: getHomeActionSummary,
  });
  const { data: preferences } = useQuery({
    queryKey: ["user-preferences"],
    queryFn: getPreferences,
  });
  const { data: snapshotResponse, isLoading: insightsLoading } = useQuery({
    queryKey: ["home-intelligence-snapshot"],
    queryFn: getIntelligenceSnapshot,
  });
  const { data: documents = [], isLoading: documentsLoading } = useAllDocuments();

  const persona = normalizeHomePersona(preferences?.intelligence.home_persona);
  const profile = homePersonaProfile(persona);
  const focusItems = preferences?.intelligence.home_focus ?? DEFAULT_FOCUS;
  const snapshot = snapshotResponse?.snapshot;
  const allInsights = useMemo(
    () => snapshot?.results.flatMap((result) => result.insights) ?? [],
    [snapshot],
  );
  const rankedInsights = useMemo(
    () => rankHomeInsights(allInsights, persona, focusItems),
    [allInsights, focusItems, persona],
  );
  const performanceInsight = useMemo(
    () => selectPerformanceInsight(rankedInsights),
    [rankedInsights],
  );
  const performanceChart = useMemo(
    () => (performanceInsight?.chart ? toItsmPerformanceChart(performanceInsight.chart) : null),
    [performanceInsight],
  );
  const developments = useMemo(
    () => buildHomeDevelopments(allInsights, documents, persona, focusItems),
    [allInsights, documents, focusItems, persona],
  );
  const risks = rankedInsights.filter((card) => RISK_SEVERITIES.has(card.severity));
  const opportunities = rankedInsights.filter((card) =>
    OPPORTUNITY_SEVERITIES.has(card.severity),
  );
  const topInsight = rankedInsights[0];
  const briefHeadline =
    topInsight?.title ?? "Your executive briefing is ready for new project signals";
  const briefBody =
    topInsight?.summary ??
    snapshot?.synthesis?.body ??
    "Tablescope will summarize material developments here as AI insights and indexed project documents become available.";

  const saveSettings = useMutation({
    mutationFn: (settings: { persona: typeof persona; focusItems: string[] }) =>
      updatePreferences({
        home_persona: settings.persona,
        home_focus: settings.focusItems,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["user-preferences"] });
      setSettingsOpen(false);
    },
  });

  useEffect(() => {
    onPersonalize?.(() => setSettingsOpen(true));
  }, [onPersonalize]);

  const highlights = actionSummary?.highlights ?? {
    needs_attention: 0,
    due_this_week: 0,
    recently_completed: 0,
  };
  const metricValues = [
    projectCount,
    risks.length,
    opportunities.length,
    highlights.due_this_week,
  ];

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1.5 flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
            <IconSparkles size={14} className="text-brand-500" />
            {profile.label} perspective · Personal business briefing
          </div>
          <h1 className="text-h1 text-ink-primary">{greetingText}</h1>
          <p className="mt-1 max-w-4xl text-body text-ink-tertiary">
            {profile.purpose}
          </p>
        </div>
        <Button variant="brandSoft" size="md" onClick={() => setSettingsOpen(true)}>
          <IconSettings2 size={15} />
          {profile.label} view
        </Button>
      </header>

      <section className="rounded-xl border border-line-tertiary bg-white p-5">
        <div className="flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
          <IconBriefcase size={15} className="text-brand-500" />
          Executive brief
        </div>
        <h2 className="mt-2 max-w-5xl text-h2 text-ink-primary">{briefHeadline}</h2>
        <p className="mt-1.5 max-w-5xl text-body leading-relaxed text-ink-secondary">
          {truncate(briefBody, 260)}
        </p>
        {topInsight ? (
          <Link
            href={`/business-insight/analysis/${encodeURIComponent(topInsight.insightId || topInsight.id)}`}
            className="mt-3 inline-flex items-center gap-1 text-small font-medium text-brand-700 hover:underline"
          >
            Review supporting insight <IconArrowUpRight size={14} />
          </Link>
        ) : null}
      </section>

      <section aria-label="Executive metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {profile.metricLabels.map((label, index) => (
          <article
            key={label}
            className="rounded-xl border border-[#DBE4F2] bg-[#DBE4F2] px-4 py-3.5"
          >
            <p className="text-caption font-medium uppercase tracking-wide text-ink-secondary">
              {label}
            </p>
            <p className="mt-1 text-[26px] font-bold leading-tight text-ink-primary">
              {actionsLoading && index === 3 ? "—" : metricValues[index]}
            </p>
          </article>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,.75fr)]">
        <article className="min-h-[330px] rounded-xl border border-line-tertiary bg-bg-primary p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <IconChartLine size={16} className="text-brand-500" />
                <h2 className="text-h3 text-ink-primary">Company performance</h2>
              </div>
              <p className="mt-0.5 text-small text-ink-tertiary">
                {performanceInsight?.title ?? "The highest-priority performance trend for this view."}
              </p>
            </div>
            {performanceInsight ? (
              <Link
                href={`/business-insight/analysis/${encodeURIComponent(performanceInsight.insightId || performanceInsight.id)}`}
                className="inline-flex shrink-0 items-center gap-1 text-caption font-medium text-brand-700 hover:underline"
              >
                Explore <IconArrowUpRight size={13} />
              </Link>
            ) : null}
          </div>
          <div className="mt-4 min-h-[230px] rounded-lg bg-[#F1F1F2] p-2">
            {performanceChart ? (
              <div style={{ height: 230 }}>
                <OperationalChart chart={performanceChart} className="h-full" />
              </div>
            ) : insightsLoading ? (
              <div className="h-[230px] animate-pulse rounded-lg bg-bg-secondary" />
            ) : (
              <div className="flex h-[230px] items-center justify-center rounded-lg px-8 text-center text-small text-ink-tertiary">
                Generate or pin a chart-backed insight to establish the primary company performance view.
              </div>
            )}
          </div>
        </article>

        <article className="rounded-xl border border-line-tertiary bg-[#FCFCFC] p-4">
          <div className="flex items-center gap-2">
            <IconSparkles size={16} className="text-brand-500" />
            <h2 className="text-h3 text-ink-primary">Key developments</h2>
          </div>
          <p className="mt-0.5 text-small text-ink-tertiary">
            Ranked AI findings and project documents for the {profile.label} lens.
          </p>
          <div className="mt-3 divide-y divide-line-tertiary">
            {developments.length ? (
              developments.map((development) => {
                const DevelopmentIcon =
                  development.kind === "document" ? IconFileText : IconSparkles;
                return (
                  <Link
                    key={`${development.kind}-${development.id}`}
                    href={development.href}
                    className="group flex gap-3 py-3 first:pt-1 last:pb-0"
                  >
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-bg-primary text-brand-500">
                      <DevelopmentIcon size={15} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <strong className="truncate text-small font-medium text-ink-primary group-hover:text-brand-700">
                          {development.title}
                        </strong>
                        <span className="shrink-0 rounded-full bg-bg-primary px-2 py-0.5 text-[10px] font-medium capitalize text-ink-tertiary">
                          {development.badge}
                        </span>
                      </span>
                      <span className="mt-0.5 block text-caption text-ink-tertiary">
                        {development.projectName} · {truncate(development.summary, 105)}
                      </span>
                    </span>
                  </Link>
                );
              })
            ) : insightsLoading || documentsLoading ? (
              <div className="space-y-3 py-2">
                {[0, 1, 2].map((item) => (
                  <div key={item} className="h-14 animate-pulse rounded-lg bg-bg-primary" />
                ))}
              </div>
            ) : (
              <p className="py-10 text-center text-small text-ink-tertiary">
                Key developments will appear as insights and documents are analyzed.
              </p>
            )}
          </div>
        </article>
      </section>

      <section className="grid gap-3 lg:grid-cols-3">
        <article className="rounded-xl border border-line-tertiary bg-[#FCFCFC] p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-[13px] font-medium text-ink-primary">
              <IconAlertTriangle size={16} className="text-danger" /> Material risks
            </span>
            <strong className="text-h2 text-ink-primary">{risks.length}</strong>
          </div>
          <p className="mt-3 min-h-10 text-small leading-relaxed text-ink-tertiary">
            {risks[0] ? truncate(risks[0].summary) : "No material AI risk signals are available for this view."}
          </p>
          {risks[0] ? (
            <Link
              href={`/business-insight/analysis/${encodeURIComponent(risks[0].insightId || risks[0].id)}`}
              className="mt-3 inline-flex items-center gap-1 text-caption font-medium text-brand-700 hover:underline"
            >
              Review risk <IconArrowUpRight size={13} />
            </Link>
          ) : null}
        </article>

        <article className="rounded-xl border border-line-tertiary bg-[#FCFCFC] p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-[13px] font-medium text-ink-primary">
              <IconTargetArrow size={16} className="text-emerald-600" /> Opportunities
            </span>
            <strong className="text-h2 text-ink-primary">{opportunities.length}</strong>
          </div>
          <p className="mt-3 min-h-10 text-small leading-relaxed text-ink-tertiary">
            {opportunities[0]
              ? truncate(opportunities[0].summary)
              : "No AI opportunity signals are available for this view."}
          </p>
          {opportunities[0] ? (
            <Link
              href={`/business-insight/analysis/${encodeURIComponent(opportunities[0].insightId || opportunities[0].id)}`}
              className="mt-3 inline-flex items-center gap-1 text-caption font-medium text-brand-700 hover:underline"
            >
              Review opportunity <IconArrowUpRight size={13} />
            </Link>
          ) : null}
        </article>

        <article className="rounded-xl border border-line-tertiary bg-[#FCFCFC] p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-[13px] font-medium text-ink-primary">
              <IconCalendarDue size={16} className="text-amber-600" /> Assigned actions
            </span>
            <strong className="text-h2 text-ink-primary">
              {actionsLoading ? "—" : actionSummary?.assigned.length ?? 0}
            </strong>
          </div>
          <p className="mt-3 min-h-10 text-small leading-relaxed text-ink-tertiary">
            {assignedSummary(actionSummary?.assigned ?? [])}
          </p>
          {actionSummary?.assigned[0] ? (() => {
            const action = actionSummary.assigned[0];
            const due = dueLabel(action.due_date);
            return (
              <Link
                href={`/projects/${action.project_id}/actions`}
                className="mt-3 flex items-center justify-between gap-3 text-caption"
              >
                <span className="min-w-0 truncate font-medium text-brand-700 hover:underline">
                  {action.title}
                </span>
                <span className={due.overdue ? "shrink-0 font-medium text-danger" : "shrink-0 text-ink-tertiary"}>
                  {due.text}
                </span>
              </Link>
            );
          })() : (
            <span className="mt-3 inline-flex items-center gap-1 text-caption text-emerald-700">
              <IconCircleCheck size={13} /> You are up to date
            </span>
          )}
        </article>
      </section>

      <HomeSettingsDialog
        open={settingsOpen}
        persona={persona}
        focusItems={focusItems}
        saving={saveSettings.isPending}
        onClose={() => setSettingsOpen(false)}
        onSave={(settings) => saveSettings.mutate(settings)}
      />
    </div>
  );
}
