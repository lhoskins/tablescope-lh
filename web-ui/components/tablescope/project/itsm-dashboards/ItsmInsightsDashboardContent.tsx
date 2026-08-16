"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IconArrowLeft, IconRefresh, IconX } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { ItsmChart } from "./ItsmChart";
import { ItsmMetricCard } from "./ItsmMetricCard";
import type {
  ItsmCardSize,
  ItsmChart as ItsmChartType,
  ItsmDashboardLayout,
  ItsmDashboardResult,
  ItsmMetricDrilldown,
  ItsmMetricValue,
} from "./types";
import styles from "./ItsmDashboardScreen.module.css";

const INSIGHT_LABELS: Record<string, string> = {
  incident_insights: "Incident Management Insights",
  service_request_insights: "Request Management Insights",
};

const PERIODS = [
  ["30_days", "30 days"],
  ["60_days", "60 days"],
  ["90_days", "90 days"],
  ["6_months", "6 months"],
  ["1_year", "1 Year"],
  ["2_years", "2 Years"],
] as const;

type PeriodKey = (typeof PERIODS)[number][0];

interface ItsmInsightsDashboardContentProps {
  projectId: string;
  preset: string;
  onBack: () => void;
}

interface DrawerState {
  open: boolean;
  title: string;
  metric?: ItsmMetricValue;
  chart?: ItsmChartType;
  selection?: { name: string; value: number | null };
}

const DEFAULT_CARD_SIZE: ItsmCardSize = "compact";
const SIZE_CYCLE: ItsmCardSize[] = ["compact", "standard", "wide"];

function readSessionDashboard(key: string): ItsmDashboardResult | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const value = sessionStorage.getItem(key);
    return value ? (JSON.parse(value) as { data: ItsmDashboardResult }).data : undefined;
  } catch {
    return undefined;
  }
}

function formatPrevious(metric: ItsmMetricValue): string {
  if (metric.previousValue === null || metric.previousValue === undefined) return "—";
  if (metric.unit === "percent") return `${metric.previousValue.toFixed(1)}%`;
  if (metric.unit === "hours") return `${metric.previousValue.toFixed(1)} hr`;
  if (metric.unit === "days") return `${metric.previousValue.toFixed(1)} days`;
  if (metric.unit === "count") return Math.round(metric.previousValue).toLocaleString();
  return metric.previousValue.toFixed(1);
}

function toneClass(tone: string): string {
  if (tone === "critical") return "bg-rose-500";
  if (tone === "warning") return "bg-amber-500";
  if (tone === "positive") return "bg-emerald-500";
  return "bg-blue-500";
}

export function ItsmInsightsDashboardContent({
  projectId,
  preset,
  onBack,
}: ItsmInsightsDashboardContentProps) {
  const queryClient = useQueryClient();
  const [selectedPreset, setSelectedPreset] = useState(preset);
  const [period, setPeriod] = useState<PeriodKey>("1_year");
  const [site, setSite] = useState("all");
  const [dimension, setDimension] = useState<"site" | "region">("site");
  const [editingLayout, setEditingLayout] = useState(false);
  const [layout, setLayout] = useState<ItsmDashboardLayout>({ order: [], sizes: {} });
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false);
  const [manualRefreshing, setManualRefreshing] = useState(false);
  const [drawer, setDrawer] = useState<DrawerState>({ open: false, title: "" });
  const draggedMetric = useRef<string | null>(null);
  const draggedChart = useRef<string | null>(null);
  const refreshedKeys = useRef(new Set<string>());

  useEffect(() => {
    setSelectedPreset(preset);
    setSite("all");
  }, [preset]);

  const queryKey = ["project", projectId, "itsm-insights", selectedPreset, period, site, dimension] as const;
  const cacheToken = queryKey.join(":");
  const browserCacheKey = `itsm-dashboard:${cacheToken}`;
  const siteQuery = site === "all" ? "" : `&site=${encodeURIComponent(site)}`;
  const dashboardUrl = `/api/projects/${projectId}/itsm-dashboards/${selectedPreset}?durationUnit=hours&period=${period}${siteQuery}&dimension=${dimension}`;

  const {
    data: dashboard,
    isLoading,
    isFetching,
    error,
  } = useQuery<ItsmDashboardResult>({
    queryKey,
    queryFn: () => apiClient.get<ItsmDashboardResult>(dashboardUrl),
    enabled: Boolean(projectId && selectedPreset),
    initialData: () => readSessionDashboard(browserCacheKey),
    refetchOnMount: "always",
    staleTime: 5 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  useEffect(() => {
    if (!dashboard || typeof window === "undefined") return;
    try {
      sessionStorage.setItem(browserCacheKey, JSON.stringify({ storedAt: Date.now(), data: dashboard }));
    } catch {
      // React Query remains the in-memory fallback when storage is unavailable.
    }
  }, [browserCacheKey, dashboard]);

  useEffect(() => {
    if (!dashboard || isFetching || refreshedKeys.current.has(cacheToken)) return;
    refreshedKeys.current.add(cacheToken);
    if (dashboard.dataQuality.cacheStatus === "miss" || dashboard.dataQuality.cacheStatus === "refreshed") return;
    let cancelled = false;
    setBackgroundRefreshing(true);
    apiClient
      .get<ItsmDashboardResult>(`${dashboardUrl}&refresh=true`)
      .then((liveDashboard) => {
        if (!cancelled) queryClient.setQueryData(queryKey, liveDashboard);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setBackgroundRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cacheToken, dashboard, dashboardUrl, isFetching, queryClient, queryKey]);

  const layoutStorageKey = `itsm-layout:${projectId}:${selectedPreset}:insights`;
  useEffect(() => {
    if (!dashboard || typeof window === "undefined") return;
    let saved: ItsmDashboardLayout | undefined;
    try {
      const raw = localStorage.getItem(layoutStorageKey);
      saved = raw ? (JSON.parse(raw) as ItsmDashboardLayout) : undefined;
    } catch {
      saved = undefined;
    }
    const metricKeys = dashboard.metrics.map((metric) => metric.metricKey);
    const chartKeys = dashboard.charts.map((chart) => chart.chartKey);
    setLayout({
      order: [
        ...(saved?.order.filter((key) => metricKeys.includes(key)) ?? []),
        ...metricKeys.filter((key) => !saved?.order.includes(key)),
      ],
      sizes: Object.fromEntries(metricKeys.map((key) => [key, saved?.sizes[key] ?? DEFAULT_CARD_SIZE])),
      chartOrder: [...(saved?.chartOrder?.filter((key) => chartKeys.includes(key)) ?? []), ...chartKeys.filter((key) => !saved?.chartOrder?.includes(key))],
      chartHeights: Object.fromEntries(chartKeys.map((key) => [key, saved?.chartHeights?.[key] ?? "standard"])),
    });
  }, [dashboard?.dashboard, dashboard?.metrics.length, layoutStorageKey]);

  useEffect(() => {
    if (!layout.order.length || typeof window === "undefined") return;
    try {
      localStorage.setItem(layoutStorageKey, JSON.stringify(layout));
    } catch {
      // Layout persistence is a convenience and should not block rendering.
    }
  }, [layout, layoutStorageKey]);

  const orderedMetrics = useMemo(() => {
    if (!dashboard) return [];
    const byKey = new Map(dashboard.metrics.map((metric) => [metric.metricKey, metric]));
    return [
      ...layout.order.map((key) => byKey.get(key)).filter((metric): metric is ItsmMetricValue => Boolean(metric)),
      ...dashboard.metrics.filter((metric) => !layout.order.includes(metric.metricKey)),
    ];
  }, [dashboard, layout.order]);
  const orderedCharts = useMemo(() => { if (!dashboard) return []; const byKey = new Map(dashboard.charts.map((chart) => [chart.chartKey, chart])); return [...(layout.chartOrder ?? []).map((key) => byKey.get(key)).filter(Boolean), ...dashboard.charts.filter((chart) => !layout.chartOrder?.includes(chart.chartKey))] as ItsmChartType[]; }, [dashboard, layout.chartOrder]);

  const { data: drilldownData, isLoading: drilldownLoading } = useQuery<ItsmMetricDrilldown>({
    queryKey: ["project", projectId, "itsm-insight-drilldown", selectedPreset, drawer.metric?.metricKey, period, site],
    queryFn: () =>
      apiClient.get<ItsmMetricDrilldown>(
        `/api/projects/${projectId}/itsm-dashboards/${selectedPreset}/metrics/${drawer.metric?.metricKey}/drilldown?durationUnit=hours&period=${period}${siteQuery}`,
      ),
    enabled: Boolean(drawer.open && drawer.metric),
    staleTime: 5 * 60 * 1000,
  });

  const openMetric = (metric: ItsmMetricValue) => {
    setDrawer({ open: true, title: metric.label, metric });
  };

  const openChart = (chart: ItsmChartType) => (name: string, value: number | null) => {
    const metric = dashboard?.metrics.find((item) => item.metricKey === chart.drilldownMetricKey);
    setDrawer({ open: true, title: chart.title, chart, metric, selection: { name, value } });
  };

  const closeDrawer = () => setDrawer((current) => ({ ...current, open: false }));

  const handleDrop = (targetKey: string) => {
    const sourceKey = draggedMetric.current;
    if (!sourceKey || sourceKey === targetKey) return;
    setLayout((current) => {
      const order = [...current.order];
      const source = order.indexOf(sourceKey), target = order.indexOf(targetKey);
      if (source < 0 || target < 0) return current;
      order.splice(source, 1);
      order.splice(target, 0, sourceKey);
      return { ...current, order };
    });
    draggedMetric.current = null;
  };

  const cycleCardSize = (metricKey: string) => {
    setLayout((current) => {
      const currentSize = current.sizes[metricKey] ?? DEFAULT_CARD_SIZE;
      const nextSize = SIZE_CYCLE[(SIZE_CYCLE.indexOf(currentSize) + 1) % SIZE_CYCLE.length];
      return { ...current, sizes: { ...current.sizes, [metricKey]: nextSize } };
    });
  };
  const handleChartDrop = (targetKey: string) => { const sourceKey = draggedChart.current; if (!sourceKey || sourceKey === targetKey) return; setLayout((current) => { const order = [...(current.chartOrder ?? [])]; const source = order.indexOf(sourceKey), target = order.indexOf(targetKey); if (source < 0 || target < 0) return current; order.splice(source, 1); order.splice(target, 0, sourceKey); return { ...current, chartOrder: order }; }); };
  const cycleChartHeight = (key: string) => setLayout((current) => { const cycle = ["compact", "standard", "tall"] as const; const height = current.chartHeights?.[key] ?? "standard"; return { ...current, chartHeights: { ...(current.chartHeights ?? {}), [key]: cycle[(cycle.indexOf(height) + 1) % cycle.length] } }; });

  const resetLayout = () => {
    if (!dashboard) return;
    const metricKeys = dashboard.metrics.map((metric) => metric.metricKey);
    setLayout({
      order: metricKeys,
      sizes: Object.fromEntries(metricKeys.map((key) => [key, DEFAULT_CARD_SIZE])),
      chartOrder: dashboard.charts.map((chart) => chart.chartKey),
      chartHeights: Object.fromEntries(dashboard.charts.map((chart) => [chart.chartKey, "standard"])),
    });
  };

  const forceRefresh = async () => {
    setManualRefreshing(true);
    try {
      const liveDashboard = await apiClient.get<ItsmDashboardResult>(`${dashboardUrl}&refresh=true`);
      queryClient.setQueryData(queryKey, liveDashboard);
    } finally {
      setManualRefreshing(false);
    }
  };

  const cardClass = (size: ItsmCardSize) =>
    size === "wide" ? styles.cardWide : size === "standard" ? styles.cardStandard : styles.cardCompact;
  const charts = orderedCharts;

  return (
    <div className={cn("space-y-3", styles.dashboardContainer)}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to dashboards"
            className="mt-1 rounded-md p-1 text-ink-tertiary hover:bg-brand-50/60 hover:text-ink-primary"
          >
            <IconArrowLeft size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-h2 text-ink-primary">{INSIGHT_LABELS[selectedPreset]}</h1>
              {dashboard && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">Live</span>}
            </div>
            <p className="text-xs text-ink-tertiary">
              Operational patterns, contributors and recommended actions
              {dashboard && ` · ${dashboard.dataQuality.reportingPeriod ?? dashboard.dataQuality.latestCompleteMonth}`}
              {(backgroundRefreshing || isFetching) && " · refreshing in background"}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <label className="sr-only" htmlFor="itsm-insight-period">Period</label>
          <select
            id="itsm-insight-period"
            value={period}
            onChange={(event) => setPeriod(event.target.value as PeriodKey)}
            className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            {PERIODS.map(([value, label]) => <option key={value} value={value}>Period: {label}</option>)}
          </select>
          <label className="sr-only" htmlFor="itsm-insight-dimension">Dimension</label>
          <select
            id="itsm-insight-dimension"
            value={dimension}
            onChange={(event) => { const next = event.target.value as "site" | "region"; setDimension(next); setSite("all"); }}
            className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="site">Site</option>
            <option value="region">Region</option>
          </select>
          <label className="flex h-8 items-center gap-1 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs">
            <span className="text-ink-secondary">{dimension === "region" ? "Region:" : "Site:"}</span>
            <select value={site} onChange={(event) => setSite(event.target.value)} aria-label={dimension} className="h-full border-0 bg-transparent pr-2"><option value="all">All {dimension === "region" ? "regions" : "sites"}</option>{dashboard?.dataQuality.availableSites?.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select>
          </label>
          <label className="sr-only" htmlFor="itsm-insight-dashboard">Dashboard</label>
          <select
            id="itsm-insight-dashboard"
            value={selectedPreset}
            onChange={(event) => {
              setSelectedPreset(event.target.value);
              setSite("all");
              setDimension("site");
            }}
            className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            {Object.entries(INSIGHT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <Button variant="secondary" size="sm" onClick={() => setEditingLayout((value) => !value)}>
            {editingLayout ? "Done" : "Edit layout"}
          </Button>
          {editingLayout && <Button variant="secondary" size="sm" onClick={resetLayout}>Reset</Button>}
          <Button variant="secondary" size="sm" onClick={forceRefresh} disabled={manualRefreshing}>
            <IconRefresh size={14} className={cn(manualRefreshing && "animate-spin")} /> Refresh
          </Button>
        </div>
      </div>

      {editingLayout && (
        <div className="rounded-md border border-dashed border-brand-200 bg-brand-50/40 px-3 py-2 text-xs text-ink-secondary">
          Drag KPI cards to reorder. Use each card’s size control to cycle through compact, standard and wide.
        </div>
      )}

      {error && <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error instanceof Error ? error.message : "Failed to load dashboard"}</div>}
      {isLoading && !dashboard && <div className="py-16 text-center text-sm text-ink-tertiary">Loading insight dashboard…</div>}

      {dashboard && (
        <>
          <div className={styles.insightBrief}>
            <div>
              <div className="text-sm font-semibold text-ink-primary">Operational brief</div>
              <div className="text-[11px] text-ink-tertiary">The story behind the selected period</div>
            </div>
            <div className={styles.insightBriefGrid}>
              {(dashboard.insights ?? []).map((insight) => (
                <button
                  type="button"
                  key={insight.insightType}
                  className="grid grid-cols-[auto_1fr] gap-2 text-left"
                  onClick={() => {
                    const metric = dashboard.metrics.find((item) => item.metricKey === insight.metricKey);
                    if (metric) openMetric(metric);
                  }}
                >
                  <span className={cn("mt-1.5 h-2.5 w-2.5 rounded-full", toneClass(insight.tone))} />
                  <span>
                    <span className="block text-xs font-semibold text-ink-primary">{insight.title}</span>
                    <span className="block text-[11px] leading-4 text-ink-tertiary">{insight.detail}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className={styles.kpiGrid}>
            {orderedMetrics.map((metric) => {
              const size = layout.sizes[metric.metricKey] ?? DEFAULT_CARD_SIZE;
              return (
                <div key={metric.metricKey} className={cardClass(size)}>
                  <ItsmMetricCard
                    metric={metric}
                    size={size}
                    editing={editingLayout}
                    onClick={openMetric}
                    onResize={cycleCardSize}
                    onDragStart={(metricKey) => { draggedMetric.current = metricKey; }}
                    onDrop={handleDrop}
                  />
                </div>
              );
            })}
          </div>

          <div className={styles.insightMainGrid}>
            {charts[0] && (
              <Card draggable={editingLayout} onDragStart={() => { draggedChart.current = charts[0].chartKey; }} onDragOver={(event) => editingLayout && event.preventDefault()} onDrop={(event) => { if (editingLayout) { event.preventDefault(); handleChartDrop(charts[0].chartKey); } }} className={cn("overflow-hidden p-3", editingLayout && "cursor-grab border-dashed")}>
                <ChartHeader chart={charts[0]} editing={editingLayout} height={layout.chartHeights?.[charts[0].chartKey]} onResize={() => cycleChartHeight(charts[0].chartKey)} />
                <ItsmChart chart={charts[0]} className={layout.chartHeights?.[charts[0].chartKey] === "compact" ? "h-56" : layout.chartHeights?.[charts[0].chartKey] === "tall" ? "h-96" : "h-72"} onElementClick={openChart(charts[0])} />
              </Card>
            )}
            <div className={styles.insightSideStack}>
              {charts.slice(1, 3).map((chart) => (
                <Card key={chart.chartKey} draggable={editingLayout} onDragStart={() => { draggedChart.current = chart.chartKey; }} onDragOver={(event) => editingLayout && event.preventDefault()} onDrop={(event) => { if (editingLayout) { event.preventDefault(); handleChartDrop(chart.chartKey); } }} className={cn("overflow-hidden p-3", editingLayout && "cursor-grab border-dashed")}>
                  <ChartHeader chart={chart} editing={editingLayout} height={layout.chartHeights?.[chart.chartKey]} onResize={() => cycleChartHeight(chart.chartKey)} />
                  <ItsmChart chart={chart} className="h-52" onElementClick={openChart(chart)} />
                </Card>
              ))}
            </div>
          </div>

          <div className={styles.insightBottomGrid}>
            {charts.slice(3, 5).map((chart) => (
              <Card key={chart.chartKey} draggable={editingLayout} onDragStart={() => { draggedChart.current = chart.chartKey; }} onDragOver={(event) => editingLayout && event.preventDefault()} onDrop={(event) => { if (editingLayout) { event.preventDefault(); handleChartDrop(chart.chartKey); } }} className={cn("overflow-hidden p-3", editingLayout && "cursor-grab border-dashed")}>
                <ChartHeader chart={chart} editing={editingLayout} height={layout.chartHeights?.[chart.chartKey]} onResize={() => cycleChartHeight(chart.chartKey)} />
                <ItsmChart chart={chart} className="h-56" onElementClick={openChart(chart)} />
              </Card>
            ))}
            <Card className="p-4">
              <div className="text-sm font-semibold text-ink-primary">Best improvement opportunities</div>
              <div className="mt-1 text-[11px] text-ink-tertiary">Prioritized by operational impact</div>
              <div className="mt-4 space-y-3">
                {(dashboard.insights ?? []).map((insight, index) => (
                  <button
                    type="button"
                    key={insight.insightType}
                    className="flex w-full items-start justify-between gap-3 border-b border-line-tertiary pb-3 text-left last:border-0"
                    onClick={() => {
                      const metric = dashboard.metrics.find((item) => item.metricKey === insight.metricKey);
                      if (metric) openMetric(metric);
                    }}
                  >
                    <span>
                      <span className="block text-xs font-semibold text-ink-primary">{index + 1}. {insight.title}</span>
                      <span className="mt-0.5 block text-[11px] leading-4 text-ink-tertiary">{insight.detail}</span>
                    </span>
                    <span className="shrink-0 rounded-full bg-blue-50 px-2 py-1 text-[10px] font-semibold capitalize text-blue-600">{insight.insightType}</span>
                  </button>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}

      <InsightDrawer
        presetLabel={INSIGHT_LABELS[selectedPreset]}
        state={drawer}
        data={drilldownData}
        loading={drilldownLoading}
        onClose={closeDrawer}
      />
    </div>
  );
}

function ChartHeader({ chart, editing = false, height = "standard", onResize }: { chart: ItsmChartType; editing?: boolean; height?: "compact" | "standard" | "tall"; onResize?: () => void }) {
  return (
    <div className="mb-1 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-sm font-semibold text-ink-primary">{chart.title}</h2>
        <p className="text-[11px] text-ink-tertiary">{chart.description ?? "Select a chart mark to open its supporting detail"}</p>
      </div>
      <span className="shrink-0 rounded-full bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-600">{chart.yAxisLabel ?? chart.unit ?? "Records"}{editing && <button type="button" onClick={onResize} className="ml-1 rounded bg-white px-1">{height}</button>}</span>
    </div>
  );
}

function InsightDrawer({
  presetLabel,
  state,
  data,
  loading,
  onClose,
}: {
  presetLabel: string;
  state: DrawerState;
  data?: ItsmMetricDrilldown;
  loading: boolean;
  onClose: () => void;
}) {
  const metric = state.metric;
  return (
    <>
      <div className={cn(styles.drilldownPanel, state.open && styles.open, "bg-bg-primary shadow-2xl")} aria-hidden={!state.open}>
        <div className="flex h-full flex-col border-r border-line-tertiary">
          <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-4">
            <div>
              <div className="text-[11px] text-ink-tertiary">{presetLabel} › insight drill-down</div>
              <h2 className="text-h3 text-ink-primary">{state.title}</h2>
            </div>
            <button type="button" onClick={onClose} className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary" aria-label="Close drilldown">
              <IconX size={18} />
            </button>
          </div>

          <div className="flex-1 overflow-auto p-5">
            {metric ? (
              <div className="space-y-5 text-sm">
                {state.selection && (
                  <div className="grid grid-cols-2 gap-3 rounded-lg border border-blue-200 bg-blue-50/50 p-4">
                    <div><div className="text-[11px] text-ink-tertiary">Selected segment</div><div className="mt-1 font-semibold text-ink-primary">{state.selection.name}</div></div>
                    <div><div className="text-[11px] text-ink-tertiary">Value</div><div className="mt-1 text-xl font-semibold text-ink-primary">{state.selection.value?.toLocaleString() ?? "—"}</div></div>
                  </div>
                )}

                <div className="rounded-lg border border-line-tertiary bg-bg-secondary/40 p-4">
                  <p className="leading-6 text-ink-secondary">{state.chart?.description ?? data?.description ?? metric.description ?? "Metric details"}</p>
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <div><div className="text-[11px] text-ink-tertiary">Current</div><div className="mt-1 text-xl font-semibold text-ink-primary">{metric.displayValue}</div></div>
                    <div><div className="text-[11px] text-ink-tertiary">Prior period</div><div className="mt-1 text-base font-semibold text-ink-primary">{formatPrevious(metric)}</div></div>
                    <div><div className="text-[11px] text-ink-tertiary">Change</div><div className={cn("mt-1 text-base font-semibold", metric.outcome === "favorable" && "text-emerald-600", metric.outcome === "unfavorable" && "text-rose-600", metric.outcome === "neutral" && "text-ink-secondary")}>{metric.comparisonLabel ?? "—"}</div></div>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-line-tertiary p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">KPI calculation</div>
                    <p className="mt-2 leading-5 text-ink-primary">{state.chart?.calculation ?? data?.calculation ?? metric.calculation ?? "See metric definition."}</p>
                  </div>
                  <div className="rounded-lg border border-line-tertiary p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">Reporting basis</div>
                    <dl className="mt-2 grid grid-cols-2 gap-y-2 text-xs">
                      <dt className="text-ink-tertiary">Period</dt><dd className="text-right text-ink-primary">{metric.periodStart} – {metric.periodEnd}</dd>
                      <dt className="text-ink-tertiary">Unit</dt><dd className="text-right capitalize text-ink-primary">{metric.unit ?? "records"}</dd>
                      <dt className="text-ink-tertiary">Method</dt><dd className="text-right capitalize text-ink-primary">{metric.status}</dd>
                      <dt className="text-ink-tertiary">Desired direction</dt><dd className="text-right text-ink-primary">{metric.polarity === "higher_is_better" ? "Higher" : metric.polarity === "lower_is_better" ? "Lower" : "Context dependent"}</dd>
                    </dl>
                  </div>
                </div>

                <div>
                  <div className="mb-3">
                    <h3 className="font-semibold text-ink-primary">{data?.contributors_label ?? "Supporting breakdown"}</h3>
                    <p className="text-xs text-ink-tertiary">{data?.majority_share_percent ? `Top three account for ${data.majority_share_percent.toFixed(1)}% of measured records` : "Largest contributors to this KPI"}</p>
                  </div>
                  {loading && <div className="py-6 text-xs text-ink-tertiary">Loading supporting data…</div>}
                  {!loading && data?.contributors.length === 0 && <div className="rounded-md bg-bg-secondary px-3 py-4 text-xs text-ink-tertiary">No contributor rows were available for this period.</div>}
                  <div className="space-y-2.5">
                    {data?.contributors.map((item) => {
                      const maximum = data.contributors[0]?.value ?? 0;
                      const width = maximum && item.value ? Math.max(4, (100 * item.value) / maximum) : 0;
                      return (
                        <div key={item.name} className="grid grid-cols-[120px_1fr_auto] items-center gap-3 text-xs">
                          <span className="truncate text-ink-secondary" title={item.name}>{item.name}</span>
                          <div className="h-2 rounded-full bg-slate-200"><div className="h-2 rounded-full bg-blue-500" style={{ width: `${width}%` }} /></div>
                          <span className="min-w-14 text-right font-medium text-ink-primary">{item.display_value}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {data && data.records.length > 0 && (
                  <div>
                    <h3 className="mb-2 font-semibold text-ink-primary">High-impact record preview</h3>
                    <div className="overflow-hidden rounded-lg border border-line-tertiary">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-bg-secondary text-ink-tertiary"><tr><th className="px-3 py-2 font-medium">Record</th><th className="px-3 py-2 font-medium">Priority</th><th className="px-3 py-2 font-medium">Site</th><th className="px-3 py-2 text-right font-medium">Value</th></tr></thead>
                        <tbody>{data.records.map((record) => <tr key={record.record_id} className="border-t border-line-tertiary"><td className="max-w-40 truncate px-3 py-2 text-ink-primary" title={record.record_id}>{record.record_id}</td><td className="px-3 py-2 text-ink-secondary">{record.priority ?? "—"}</td><td className="px-3 py-2 text-ink-secondary">{record.site ?? "—"}</td><td className="px-3 py-2 text-right font-medium text-ink-primary">{record.display_value ?? "—"}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                )}

                {data?.warnings.map((warning) => <div key={warning} className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">{warning}</div>)}
              </div>
            ) : (
              <div className="text-sm text-ink-secondary">Supporting KPI detail is not available for this chart selection.</div>
            )}
          </div>
        </div>
      </div>
      {state.open && <button type="button" className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-label="Close overlay" />}
    </>
  );
}
