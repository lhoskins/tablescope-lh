"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { IconArrowLeft, IconRefresh, IconX } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import type {
  ItsmCardSize,
  ItsmDashboardLayout,
  ItsmDashboardResult,
  ItsmMetricDrilldown,
  ItsmMetricValue,
} from "./types";
import { ItsmMetricCard } from "./ItsmMetricCard";
import { ItsmChart } from "./ItsmChart";
import { ItsmInsightsDashboardContent } from "./ItsmInsightsDashboardContent";
import { useItsmDashboardQuery } from "./use-itsm-dashboard-query";
import styles from "./ItsmDashboardScreen.module.css";


export const PRESET_LABELS: Record<string, string> = {
  incident: "Incident Management",
  service_request: "Service Request Management",
  availability: "Availability & Reliability",
  productivity: "Service Desk Productivity",
  problem: "Problem Management",
  incident_insights: "Incident Management Insights",
  service_request_insights: "Request Management Insights",
};

const INSIGHT_PRESETS = new Set(["incident_insights", "service_request_insights"]);
const PERIODS = [["30_days", "30 days"], ["60_days", "60 days"], ["90_days", "90 days"], ["6_months", "6 months"], ["1_year", "1 Year"], ["2_years", "2 Years"]] as const;
type PeriodKey = (typeof PERIODS)[number][0];
type DashboardGridItem =
  | { type: "metric"; key: string; metric: ItsmMetricValue }
  | { type: "chart"; key: string; chart: ItsmDashboardResult["charts"][number] };

interface ItsmDashboardContentProps {
  projectId: string;
  preset: string;
  onBack: () => void;
}

const DEFAULT_CARD_SIZE: ItsmCardSize = "compact";
const SIZE_CYCLE: ItsmCardSize[] = ["compact", "standard", "wide"];

function formatPrevious(metric: ItsmMetricValue): string {
  if (metric.previousValue === null || metric.previousValue === undefined) return "—";
  if (metric.unit === "percent") return `${metric.previousValue.toFixed(2)}%`;
  if (metric.unit === "hours") return `${metric.previousValue.toFixed(1)} hr`;
  if (metric.unit === "minutes") return `${metric.previousValue.toFixed(1)} min`;
  if (metric.unit === "days") return `${metric.previousValue.toFixed(1)} days`;
  if (metric.unit === "count") return Math.round(metric.previousValue).toLocaleString();
  return metric.previousValue.toFixed(1);
}

function ItsmKpiDashboardContent({ projectId, preset, onBack }: ItsmDashboardContentProps) {
  const [selectedPreset, setSelectedPreset] = useState(preset);
  const [durationUnit, setDurationUnit] = useState<"hours" | "minutes">("hours");
  const [period, setPeriod] = useState<PeriodKey>("1_year");
  const [site, setSite] = useState("all");
  const [dimension, setDimension] = useState<"site" | "region">("site");
  const [editingLayout, setEditingLayout] = useState(false);
  const [layout, setLayout] = useState<ItsmDashboardLayout>({ order: [], sizes: {} });
  const draggedItem = useRef<string | null>(null);

  useEffect(() => {
    setSelectedPreset(preset);
    setSite("all");
  }, [preset]);

  const [drilldown, setDrilldown] = useState<{
    open: boolean;
    title: string;
    metric?: ItsmMetricValue;
    dimension?: { name: string; value: number | null };
  }>({ open: false, title: "" });

  const dashboardQueryKey = [
    "project",
    projectId,
    "itsm-dashboards",
    selectedPreset,
    durationUnit,
    period,
    site,
    dimension,
  ] as const;
  const siteQuery = site === "all" ? "" : `&site=${encodeURIComponent(site)}`;
  const dashboardUrl = `/api/projects/${projectId}/itsm-dashboards/${selectedPreset}?durationUnit=${durationUnit}&period=${period}${siteQuery}&dimension=${dimension}`;

  const {
    data: presets,
    isLoading: presetsLoading,
    error: presetsError,
  } = useQuery<string[]>({
    queryKey: ["project", projectId, "itsm-dashboards"],
    queryFn: () => apiClient.get<string[]>(`/api/projects/${projectId}/itsm-dashboards`),
    enabled: Boolean(projectId),
    staleTime: 60 * 60 * 1000,
  });

  const {
    dashboard,
    isLoading,
    isFetching,
    error,
    backgroundRefreshing,
    manualRefreshing,
    forceRefresh,
  } = useItsmDashboardQuery(dashboardQueryKey, dashboardUrl, Boolean(projectId && selectedPreset));

  const layoutStorageKey = `itsm-layout:${projectId}:${selectedPreset}`;
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
    const validItemKeys = [
      ...metricKeys.map((key) => `metric:${key}`),
      ...chartKeys.map((key) => `chart:${key}`),
    ];
    const legacyOrder = [
      ...(saved?.order ?? []).map((key) => `metric:${key}`),
      ...(saved?.chartOrder ?? []).map((key) => `chart:${key}`),
    ];
    const storedOrder = saved?.itemOrder ?? legacyOrder;
    setLayout({
      order: [...(saved?.order.filter((key) => metricKeys.includes(key)) ?? []), ...metricKeys.filter((key) => !saved?.order.includes(key))],
      sizes: Object.fromEntries(metricKeys.map((key) => [key, saved?.sizes[key] ?? DEFAULT_CARD_SIZE])),
      chartOrder: [...(saved?.chartOrder?.filter((key) => chartKeys.includes(key)) ?? []), ...chartKeys.filter((key) => !saved?.chartOrder?.includes(key))],
      chartHeights: Object.fromEntries(chartKeys.map((key) => [key, saved?.chartHeights?.[key] ?? "standard"])),
      chartWidths: Object.fromEntries(chartKeys.map((key) => [key, saved?.chartWidths?.[key] ?? "half"])),
      itemOrder: [
        ...storedOrder.filter((key) => validItemKeys.includes(key)),
        ...validItemKeys.filter((key) => !storedOrder.includes(key)),
      ],
    });
  }, [dashboard, layoutStorageKey]);

  useEffect(() => {
    if (!layout.itemOrder?.length || typeof window === "undefined") return;
    try {
      localStorage.setItem(layoutStorageKey, JSON.stringify(layout));
    } catch {
      // Layout persistence is a convenience and should never block the dashboard.
    }
  }, [layout, layoutStorageKey]);

  const orderedItems = useMemo<DashboardGridItem[]>(() => {
    if (!dashboard) return [];
    const metrics = new Map(dashboard.metrics.map((metric) => [`metric:${metric.metricKey}`, metric]));
    const charts = new Map(dashboard.charts.map((chart) => [`chart:${chart.chartKey}`, chart]));
    const result: DashboardGridItem[] = [];
    for (const key of layout.itemOrder ?? []) {
      if (key.startsWith("metric:")) {
        const metric = metrics.get(key);
        if (metric) result.push({ type: "metric", key, metric });
      } else {
        const chart = charts.get(key);
        if (chart) result.push({ type: "chart", key, chart });
      }
    }
    return result;
  }, [dashboard, layout.itemOrder]);

  const { data: drilldownData, isLoading: drilldownLoading } = useQuery<ItsmMetricDrilldown>({
    queryKey: ["project", projectId, "itsm-drilldown", selectedPreset, drilldown.metric?.metricKey, durationUnit, period, site],
    queryFn: () =>
      apiClient.get<ItsmMetricDrilldown>(
        `/api/projects/${projectId}/itsm-dashboards/${selectedPreset}/metrics/${drilldown.metric?.metricKey}/drilldown?durationUnit=${durationUnit}&period=${period}${siteQuery}`,
      ),
    enabled: Boolean(drilldown.open && drilldown.metric),
    staleTime: 5 * 60 * 1000,
  });

  const handleMetricClick = (metric: ItsmMetricValue) => {
    setDrilldown({ open: true, title: metric.label, metric });
  };

  const handleChartClick = (chartTitle: string) => (name: string, value: number | null) => {
    setDrilldown({ open: true, title: `${chartTitle} — ${name}`, dimension: { name, value } });
  };

  const closeDrilldown = () => setDrilldown((current) => ({ ...current, open: false }));

  const handleItemDrop = (targetKey: string) => {
    const sourceKey = draggedItem.current;
    if (!sourceKey || sourceKey === targetKey) return;
    setLayout((current) => {
      const order = [...(current.itemOrder ?? [])];
      const source = order.indexOf(sourceKey), target = order.indexOf(targetKey);
      if (source < 0 || target < 0) return current;
      order.splice(source, 1);
      order.splice(target, 0, sourceKey);
      const movingChartAcrossTypes = sourceKey.startsWith("chart:") && targetKey.startsWith("metric:");
      const chartKey = sourceKey.replace(/^chart:/, "");
      return {
        ...current,
        itemOrder: order,
        chartWidths: movingChartAcrossTypes
          ? { ...(current.chartWidths ?? {}), [chartKey]: "full" }
          : current.chartWidths,
      };
    });
    draggedItem.current = null;
  };

  const cycleCardSize = (metricKey: string) => {
    setLayout((current) => {
      const currentSize = current.sizes[metricKey] ?? DEFAULT_CARD_SIZE;
      const nextSize = SIZE_CYCLE[(SIZE_CYCLE.indexOf(currentSize) + 1) % SIZE_CYCLE.length];
      return { ...current, sizes: { ...current.sizes, [metricKey]: nextSize } };
    });
  };
  const cycleChartHeight = (key: string) => setLayout((current) => { const cycle = ["compact", "standard", "tall"] as const; const currentHeight = current.chartHeights?.[key] ?? "standard"; return { ...current, chartHeights: { ...(current.chartHeights ?? {}), [key]: cycle[(cycle.indexOf(currentHeight) + 1) % cycle.length] } }; });
  const cycleChartWidth = (key: string) => setLayout((current) => ({ ...current, chartWidths: { ...(current.chartWidths ?? {}), [key]: current.chartWidths?.[key] === "full" ? "half" : "full" } }));

  const resetLayout = () => {
    if (!dashboard) return;
    const metricKeys = dashboard.metrics.map((metric) => metric.metricKey);
    setLayout({
      order: metricKeys,
      sizes: Object.fromEntries(metricKeys.map((key) => [key, DEFAULT_CARD_SIZE])),
      chartOrder: dashboard.charts.map((chart) => chart.chartKey),
      chartHeights: Object.fromEntries(dashboard.charts.map((chart) => [chart.chartKey, "standard"])),
      chartWidths: Object.fromEntries(dashboard.charts.map((chart) => [chart.chartKey, "half"])),
      itemOrder: [
        ...metricKeys.map((key) => `metric:${key}`),
        ...dashboard.charts.map((chart) => `chart:${chart.chartKey}`),
      ],
    });
  };

  const cardClass = (size: ItsmCardSize) =>
    size === "wide" ? styles.cardWide : size === "standard" ? styles.cardStandard : styles.cardCompact;

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
              <h1 className="text-h2 text-ink-primary">
                {PRESET_LABELS[dashboard?.dashboard ?? selectedPreset] ?? (dashboard?.dashboard ?? selectedPreset)}
              </h1>
              {dashboard && (
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">
                  Live
                </span>
              )}
            </div>
            {dashboard && (
              <p className="text-xs text-ink-tertiary">
                Latest complete month {dashboard.dataQuality.latestCompleteMonth} · updated{" "}
                {new Date(dashboard.asOf).toLocaleString()}
                {(backgroundRefreshing || isFetching) && " · refreshing in background"}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <select value={period} onChange={(event) => setPeriod(event.target.value as PeriodKey)} aria-label="Period" className="h-8 rounded-md border px-2 text-xs">{PERIODS.map(([value, label]) => <option key={value} value={value}>Period: {label}</option>)}</select>
          <select
            aria-label="Dimension"
            value={dimension}
            onChange={(event) => { const next = event.target.value as "site" | "region"; setDimension(next); setSite("all"); }}
            className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="site">Site</option>
            <option value="region">Region</option>
          </select>
          <label className="flex h-8 items-center gap-1 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs"><span className="text-ink-secondary">{dimension === "region" ? "Region:" : "Site:"}</span><select value={site} onChange={(event) => setSite(event.target.value)} aria-label={dimension} className="h-full border-0 bg-transparent pr-2"><option value="all">All {dimension === "region" ? "regions" : "sites"}</option>{dashboard?.dataQuality.availableSites?.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label>
          <select
            aria-label="Duration unit"
            value={durationUnit}
            onChange={(event) => setDurationUnit(event.target.value as "hours" | "minutes")}
            className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="hours">Durations: hours</option>
            <option value="minutes">Durations: minutes</option>
          </select>
          <select
            id="itsm-preset"
            aria-label="Dashboard"
            value={selectedPreset}
            onChange={(event) => setSelectedPreset(event.target.value)}
            className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            {presetsLoading && <option>Loading…</option>}
            {presetsError && <option>Error</option>}
            {presets?.filter((item) => !INSIGHT_PRESETS.has(item)).map((item) => (
              <option key={item} value={item}>
                {PRESET_LABELS[item] ?? item}
              </option>
            ))}
          </select>
          <Button variant="secondary" size="sm" onClick={() => setEditingLayout((value) => !value)}>
            {editingLayout ? "Done" : "Edit layout"}
          </Button>
          {editingLayout && (
            <Button variant="secondary" size="sm" onClick={resetLayout}>
              Reset
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={forceRefresh} disabled={manualRefreshing}>
            <IconRefresh size={14} className={cn(manualRefreshing && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {editingLayout && (
        <div className="rounded-md border border-dashed border-brand-200 bg-brand-50/40 px-3 py-2 text-xs text-ink-secondary">
          Drag any KPI or chart into any grid position. Charts moved above KPIs expand to a full row; use the chart controls to change width and height.
        </div>
      )}

      {error && (
        <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          {error instanceof Error ? error.message : "Failed to load dashboard"}
        </div>
      )}

      {isLoading && !dashboard && (
        <div className="py-16 text-center text-sm text-ink-tertiary">Loading metrics…</div>
      )}

      {dashboard && (
          <div className={styles.kpiGrid}>
            {orderedItems.map((item) => {
              if (item.type === "metric") {
                const metric = item.metric;
              const size = layout.sizes[metric.metricKey] ?? DEFAULT_CARD_SIZE;
              return (
                <div key={item.key} className={cardClass(size)}>
                  <ItsmMetricCard
                    metric={metric}
                    size={size}
                    editing={editingLayout}
                    onClick={handleMetricClick}
                    onResize={cycleCardSize}
                    onDragStart={(metricKey) => { draggedItem.current = `metric:${metricKey}`; }}
                    onDrop={(metricKey) => handleItemDrop(`metric:${metricKey}`)}
                  />
                </div>
              );
              }
              const chart = item.chart;
              const height = layout.chartHeights?.[chart.chartKey] ?? "standard";
              const width = layout.chartWidths?.[chart.chartKey] ?? "half";
              return <div key={item.key} className={width === "full" ? styles.chartFull : styles.chartHalf}>
                <Card draggable={editingLayout} onDragStart={() => { draggedItem.current = `chart:${chart.chartKey}`; }} onDragOver={(event) => editingLayout && event.preventDefault()} onDrop={(event) => { if (editingLayout) { event.preventDefault(); handleItemDrop(`chart:${chart.chartKey}`); } }} className={cn("h-full overflow-hidden p-3", editingLayout && "cursor-grab border-dashed")}>
                <div className="mb-1 flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-ink-primary">{chart.title}</h2>
                    <p className="text-[11px] text-ink-tertiary">
                      Select a chart mark to open its filtered details
                    </p>
                  </div>
                  <span className="flex shrink-0 items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-600">
                    {chart.yAxisLabel ?? chart.unit ?? "Records"}
                    {editingLayout && <><button type="button" onClick={() => cycleChartWidth(chart.chartKey)} className="rounded bg-white px-1">{width === "full" ? "Full" : "½"}</button><button type="button" onClick={() => cycleChartHeight(chart.chartKey)} className="rounded bg-white px-1">{height}</button></>}
                  </span>
                </div>
                <ItsmChart chart={chart} className={height === "compact" ? "h-44" : height === "tall" ? "h-80" : "h-56"} onElementClick={handleChartClick(chart.title)} />
                </Card>
              </div>;
            })}
          </div>
      )}

      <div
        className={cn(styles.drilldownPanel, drilldown.open && styles.open, "bg-bg-primary shadow-2xl")}
        aria-hidden={!drilldown.open}
      >
        <div className="flex h-full flex-col border-r border-line-tertiary">
          <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-4">
            <div>
              <div className="text-[11px] text-ink-tertiary">
                {PRESET_LABELS[selectedPreset]} › KPI drill-down
              </div>
              <h2 className="text-h3 text-ink-primary">{drilldown.title}</h2>
            </div>
            <button
              onClick={closeDrilldown}
              className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
              aria-label="Close drilldown"
            >
              <IconX size={18} />
            </button>
          </div>

          <div className="flex-1 overflow-auto p-5">
            {drilldown.metric && (
              <div className="space-y-5 text-sm">
                <div className="rounded-lg border border-line-tertiary bg-bg-secondary/40 p-4">
                  <p className="text-sm leading-6 text-ink-secondary">
                    {drilldownData?.description ?? drilldown.metric.description ?? "Metric details"}
                  </p>
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <div>
                      <div className="text-[11px] text-ink-tertiary">Current</div>
                      <div className="mt-1 text-xl font-semibold text-ink-primary">
                        {drilldown.metric.displayValue}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-ink-tertiary">Prior month</div>
                      <div className="mt-1 text-base font-semibold text-ink-primary">
                        {formatPrevious(drilldown.metric)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-ink-tertiary">Change</div>
                      <div
                        className={cn(
                          "mt-1 text-base font-semibold",
                          drilldown.metric.outcome === "favorable" && "text-emerald-600",
                          drilldown.metric.outcome === "unfavorable" && "text-rose-600",
                          drilldown.metric.outcome === "neutral" && "text-ink-secondary",
                        )}
                      >
                        {drilldown.metric.comparisonLabel ?? "—"}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-line-tertiary p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                      Calculation
                    </div>
                    <p className="mt-2 leading-5 text-ink-primary">
                      {drilldownData?.calculation ?? drilldown.metric.calculation ?? "See metric definition."}
                    </p>
                  </div>
                  <div className="rounded-lg border border-line-tertiary p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                      Reporting basis
                    </div>
                    <dl className="mt-2 grid grid-cols-2 gap-y-2 text-xs">
                      <dt className="text-ink-tertiary">Period</dt>
                      <dd className="text-right text-ink-primary">
                        {drilldown.metric.periodStart} – {drilldown.metric.periodEnd}
                      </dd>
                      <dt className="text-ink-tertiary">Unit</dt>
                      <dd className="text-right capitalize text-ink-primary">
                        {drilldown.metric.unit ?? "records"}
                      </dd>
                      <dt className="text-ink-tertiary">Method</dt>
                      <dd className="text-right capitalize text-ink-primary">{drilldown.metric.status}</dd>
                    </dl>
                  </div>
                </div>

                <div>
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div>
                      <h3 className="font-semibold text-ink-primary">
                        {drilldownData?.contributors_label ?? "Supporting breakdown"}
                      </h3>
                      <p className="text-xs text-ink-tertiary">
                        {drilldownData?.majority_share_percent
                          ? `Top three account for ${drilldownData.majority_share_percent.toFixed(2)}% of measured records`
                          : "Largest contributors to this KPI"}
                      </p>
                    </div>
                  </div>
                  {drilldownLoading && <div className="py-6 text-xs text-ink-tertiary">Loading supporting data…</div>}
                  {!drilldownLoading && drilldownData?.contributors.length === 0 && (
                    <div className="rounded-md bg-bg-secondary px-3 py-4 text-xs text-ink-tertiary">
                      No contributor rows were available for this period.
                    </div>
                  )}
                  <div className="space-y-2.5">
                    {drilldownData?.contributors.map((item) => {
                      const maximum = drilldownData.contributors[0]?.value ?? 0;
                      const width = maximum && item.value ? Math.max(4, (100 * item.value) / maximum) : 0;
                      return (
                        <div key={item.name} className="grid grid-cols-[120px_1fr_auto] items-center gap-3 text-xs">
                          <span className="truncate text-ink-secondary" title={item.name}>
                            {item.name}
                          </span>
                          <div className="h-2 rounded-full bg-slate-200">
                            <div className="h-2 rounded-full bg-blue-500" style={{ width: `${width}%` }} />
                          </div>
                          <span className="min-w-14 text-right font-medium text-ink-primary">{item.display_value}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {drilldownData && drilldownData.records.length > 0 && (
                  <div>
                    <h3 className="mb-2 font-semibold text-ink-primary">High-impact record preview</h3>
                    <div className="overflow-hidden rounded-lg border border-line-tertiary">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-bg-secondary text-ink-tertiary">
                          <tr>
                            <th className="px-3 py-2 font-medium">Record</th>
                            <th className="px-3 py-2 font-medium">Priority</th>
                            <th className="px-3 py-2 font-medium">Site</th>
                            <th className="px-3 py-2 text-right font-medium">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {drilldownData.records.map((record) => (
                            <tr key={record.record_id} className="border-t border-line-tertiary">
                              <td className="max-w-40 truncate px-3 py-2 text-ink-primary" title={record.record_id}>
                                {record.record_id}
                              </td>
                              <td className="px-3 py-2 text-ink-secondary">{record.priority ?? "—"}</td>
                              <td className="px-3 py-2 text-ink-secondary">{record.site ?? "—"}</td>
                              <td className="px-3 py-2 text-right font-medium text-ink-primary">
                                {record.display_value ?? "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {drilldownData?.warnings.map((warning) => (
                  <div key={warning} className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
                    {warning}
                  </div>
                ))}
              </div>
            )}

            {drilldown.dimension && (
              <div className="space-y-4 text-sm">
                <p className="text-ink-secondary">
                  This chart selection is scoped to the displayed reporting period.
                </p>
                <div className="grid grid-cols-2 gap-3 rounded-lg border border-line-tertiary p-4">
                  <div>
                    <div className="text-[11px] text-ink-tertiary">Selection</div>
                    <div className="mt-1 font-semibold text-ink-primary">{drilldown.dimension.name}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-ink-tertiary">Value</div>
                    <div className="mt-1 text-xl font-semibold text-ink-primary">
                      {drilldown.dimension.value?.toLocaleString() ?? "—"}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {drilldown.open && (
        <button
          className="fixed inset-0 z-40 bg-black/20"
          onClick={closeDrilldown}
          aria-label="Close overlay"
        />
      )}
    </div>
  );
}

export function ItsmDashboardContent(props: ItsmDashboardContentProps) {
  if (INSIGHT_PRESETS.has(props.preset)) {
    return <ItsmInsightsDashboardContent {...props} />;
  }
  return <ItsmKpiDashboardContent {...props} />;
}
