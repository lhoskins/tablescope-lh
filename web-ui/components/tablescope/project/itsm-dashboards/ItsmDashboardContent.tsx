"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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

interface ItsmDashboardContentProps {
  projectId: string;
  preset: string;
  onBack: () => void;
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
  if (metric.unit === "minutes") return `${metric.previousValue.toFixed(1)} min`;
  if (metric.unit === "days") return `${metric.previousValue.toFixed(1)} days`;
  if (metric.unit === "count") return Math.round(metric.previousValue).toLocaleString();
  return metric.previousValue.toFixed(1);
}

function ItsmKpiDashboardContent({ projectId, preset, onBack }: ItsmDashboardContentProps) {
  const queryClient = useQueryClient();
  const [selectedPreset, setSelectedPreset] = useState(preset);
  const [durationUnit, setDurationUnit] = useState<"hours" | "minutes">("hours");
  const [editingLayout, setEditingLayout] = useState(false);
  const [layout, setLayout] = useState<ItsmDashboardLayout>({ order: [], sizes: {} });
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false);
  const [manualRefreshing, setManualRefreshing] = useState(false);
  const draggedMetric = useRef<string | null>(null);
  const refreshedKeys = useRef(new Set<string>());

  useEffect(() => {
    setSelectedPreset(preset);
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
  ] as const;
  const cacheToken = dashboardQueryKey.join(":");
  const browserCacheKey = `itsm-dashboard:${cacheToken}`;
  const dashboardUrl = `/api/projects/${projectId}/itsm-dashboards/${selectedPreset}?durationUnit=${durationUnit}`;

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
    data: dashboard,
    isLoading,
    isFetching,
    error,
  } = useQuery<ItsmDashboardResult>({
    queryKey: dashboardQueryKey,
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
      // Storage may be unavailable in private browsing; React Query still caches in memory.
    }
  }, [browserCacheKey, dashboard]);

  useEffect(() => {
    if (!dashboard || isFetching || refreshedKeys.current.has(cacheToken)) return;
    refreshedKeys.current.add(cacheToken);
    if (dashboard.dataQuality.cacheStatus === "miss" || dashboard.dataQuality.cacheStatus === "refreshed") {
      return;
    }
    let cancelled = false;
    setBackgroundRefreshing(true);
    apiClient
      .get<ItsmDashboardResult>(`${dashboardUrl}&refresh=true`)
      .then((liveDashboard) => {
        if (!cancelled) queryClient.setQueryData(dashboardQueryKey, liveDashboard);
      })
      .catch(() => {
        // Keep the instantly rendered cached snapshot if background refresh fails.
      })
      .finally(() => {
        if (!cancelled) setBackgroundRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cacheToken, dashboard, dashboardQueryKey, dashboardUrl, isFetching, queryClient]);

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
    setLayout({
      order: [...(saved?.order.filter((key) => metricKeys.includes(key)) ?? []), ...metricKeys.filter((key) => !saved?.order.includes(key))],
      sizes: Object.fromEntries(metricKeys.map((key) => [key, saved?.sizes[key] ?? DEFAULT_CARD_SIZE])),
    });
  }, [dashboard?.dashboard, dashboard?.metrics.length, layoutStorageKey]);

  useEffect(() => {
    if (!layout.order.length || typeof window === "undefined") return;
    try {
      localStorage.setItem(layoutStorageKey, JSON.stringify(layout));
    } catch {
      // Layout persistence is a convenience and should never block the dashboard.
    }
  }, [layout, layoutStorageKey]);

  const orderedMetrics = useMemo(() => {
    if (!dashboard) return [];
    const metrics = new Map(dashboard.metrics.map((metric) => [metric.metricKey, metric]));
    return [...layout.order.map((key) => metrics.get(key)).filter((metric): metric is ItsmMetricValue => Boolean(metric)), ...dashboard.metrics.filter((metric) => !layout.order.includes(metric.metricKey))];
  }, [dashboard, layout.order]);

  const { data: drilldownData, isLoading: drilldownLoading } = useQuery<ItsmMetricDrilldown>({
    queryKey: ["project", projectId, "itsm-drilldown", selectedPreset, drilldown.metric?.metricKey, durationUnit],
    queryFn: () =>
      apiClient.get<ItsmMetricDrilldown>(
        `/api/projects/${projectId}/itsm-dashboards/${selectedPreset}/metrics/${drilldown.metric?.metricKey}/drilldown?durationUnit=${durationUnit}`,
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

  const handleDrop = (targetKey: string) => {
    const sourceKey = draggedMetric.current;
    if (!sourceKey || sourceKey === targetKey) return;
    setLayout((current) => {
      const order = current.order.filter((key) => key !== sourceKey);
      order.splice(order.indexOf(targetKey), 0, sourceKey);
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

  const resetLayout = () => {
    if (!dashboard) return;
    const metricKeys = dashboard.metrics.map((metric) => metric.metricKey);
    setLayout({
      order: metricKeys,
      sizes: Object.fromEntries(metricKeys.map((key) => [key, DEFAULT_CARD_SIZE])),
    });
  };

  const forceRefresh = async () => {
    setManualRefreshing(true);
    try {
      const liveDashboard = await apiClient.get<ItsmDashboardResult>(`${dashboardUrl}&refresh=true`);
      queryClient.setQueryData(dashboardQueryKey, liveDashboard);
    } finally {
      setManualRefreshing(false);
    }
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
          Drag cards to reorder. Use the size control on a card to cycle between compact, standard, and wide.
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
        <>
          <div className={styles.kpiGrid}>
            {orderedMetrics.map((metric) => {
              const size = layout.sizes[metric.metricKey] ?? DEFAULT_CARD_SIZE;
              return (
                <div key={metric.metricKey} className={cardClass(size)}>
                  <ItsmMetricCard
                    metric={metric}
                    size={size}
                    editing={editingLayout}
                    onClick={handleMetricClick}
                    onResize={cycleCardSize}
                    onDragStart={(metricKey) => {
                      draggedMetric.current = metricKey;
                    }}
                    onDrop={handleDrop}
                  />
                </div>
              );
            })}
          </div>

          <div className={styles.chartGrid}>
            {dashboard.charts.map((chart) => (
              <Card key={chart.chartKey} className="overflow-hidden p-3">
                <div className="mb-1 flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-ink-primary">{chart.title}</h2>
                    <p className="text-[11px] text-ink-tertiary">
                      Select a chart mark to open its filtered details
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-600">
                    {chart.yAxisLabel ?? chart.unit ?? "Records"}
                  </span>
                </div>
                <ItsmChart chart={chart} onElementClick={handleChartClick(chart.title)} />
              </Card>
            ))}
          </div>
        </>
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
                          ? `Top three account for ${drilldownData.majority_share_percent.toFixed(1)}% of measured records`
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
