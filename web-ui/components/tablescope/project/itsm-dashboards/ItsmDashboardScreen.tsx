"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { IconRefresh, IconX } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { cn } from "@/lib/cn";
import type { ItsmDashboardResult, ItsmMetricValue } from "./types";
import { ItsmMetricCard } from "./ItsmMetricCard";
import { ItsmChart } from "./ItsmChart";
import styles from "./ItsmDashboardScreen.module.css";

const PRESET_LABELS: Record<string, string> = {
  incident: "Incident Management",
  service_request: "Service Request Management",
  availability: "Availability & Reliability",
  productivity: "Service Desk Productivity",
  problem: "Problem Management",
};

interface ItsmDashboardScreenProps {
  projectId: string;
}

export function ItsmDashboardScreen({ projectId }: ItsmDashboardScreenProps) {
  const { data: identity } = useCurrentUser();
  const [preset, setPreset] = useState<string>("incident");
  const [drilldown, setDrilldown] = useState<{
    open: boolean;
    title: string;
    metric?: ItsmMetricValue;
    dimension?: { name: string; value: number | null };
  }>({ open: false, title: "" });

  const enabled = identity?.tenant.servicenowItsmDashboardsV2Enabled ?? false;

  const {
    data: presets,
    isLoading: presetsLoading,
    error: presetsError,
  } = useQuery<string[]>({
    queryKey: ["project", projectId, "itsm-dashboards"],
    queryFn: () => apiClient.get<string[]>(`/api/projects/${projectId}/itsm-dashboards`),
    enabled,
  });

  const {
    data: dashboard,
    isLoading,
    error,
    refetch,
  } = useQuery<ItsmDashboardResult>({
    queryKey: ["project", projectId, "itsm-dashboards", preset],
    queryFn: () => apiClient.get<ItsmDashboardResult>(`/api/projects/${projectId}/itsm-dashboards/${preset}`),
    enabled,
  });

  const handleMetricClick = (metric: ItsmMetricValue) => {
    setDrilldown({ open: true, title: metric.label, metric });
  };

  const handleChartClick = (chartTitle: string) => (name: string, value: number | null) => {
    setDrilldown({ open: true, title: `${chartTitle} — ${name}`, dimension: { name, value } });
  };

  const closeDrilldown = () => setDrilldown((d) => ({ ...d, open: false }));

  if (!enabled) {
    return (
      <ProjectShell projectId={projectId} activeNav="project-itsm-dashboards" breadcrumbLabel="ITSM Dashboards">
        <div className="py-16 text-center text-sm text-ink-tertiary">
          ServiceNow ITSM dashboards are not enabled for this tenant.
        </div>
      </ProjectShell>
    );
  }

  const selector = (
    <div className="flex items-center gap-3">
      <label htmlFor="itsm-preset" className="text-sm text-ink-secondary">
        Dashboard
      </label>
      <select
        id="itsm-preset"
        value={preset}
        onChange={(e) => setPreset(e.target.value)}
        className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-sm text-ink-primary focus:border-brand-500 focus:outline-none"
      >
        {presetsLoading && <option>Loading…</option>}
        {presetsError && <option>Error</option>}
        {presets?.map((p) => (
          <option key={p} value={p}>
            {PRESET_LABELS[p] ?? p}
          </option>
        ))}
      </select>
      <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isLoading}>
        <IconRefresh size={14} className={cn(isLoading && "animate-spin")} />
        Refresh
      </Button>
    </div>
  );

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-itsm-dashboards"
      breadcrumbLabel="ITSM Dashboards"
      actions={selector}
    >
      <div className={cn("space-y-4", styles.dashboardContainer)}>
        {error && (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
            {error instanceof Error ? error.message : "Failed to load dashboard"}
          </div>
        )}

        {dashboard && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-h2 text-ink-primary">{PRESET_LABELS[dashboard.dashboard] ?? dashboard.dashboard}</h1>
                <p className="text-xs text-ink-tertiary">
                  As of {new Date(dashboard.asOf).toLocaleString()} · Latest complete month: {" "}
                  {dashboard.dataQuality.latestCompleteMonth}
                </p>
              </div>
              {dashboard.dataQuality.missingMetrics.length > 0 && (
                <div className="text-xs text-amber-600">
                  {dashboard.dataQuality.missingMetrics.length} metric(s) not yet implemented
                </div>
              )}
            </div>

            <div className={styles.kpiGrid}>
              {dashboard.metrics.map((metric) => (
                <ItsmMetricCard key={metric.metricKey} metric={metric} onClick={handleMetricClick} />
              ))}
            </div>

            <div className={styles.chartGrid}>
              {dashboard.charts.map((chart) => (
                <Card key={chart.chartKey} className="p-3">
                  <ItsmChart chart={chart} onElementClick={handleChartClick(chart.title)} />
                </Card>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Drill-down overlay */}
      <div className={cn(styles.drilldownPanel, drilldown.open && styles.open, "bg-bg-primary shadow-2xl")}>
        <div className="flex h-full flex-col border-r border-line-tertiary">
          <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
            <h2 className="text-h3 text-ink-primary">{drilldown.title}</h2>
            <button
              onClick={closeDrilldown}
              className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
              aria-label="Close drilldown"
            >
              <IconX size={18} />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4">
            {drilldown.metric && (
              <div className="space-y-4 text-sm">
                <div>
                  <span className="text-ink-secondary">Value</span>
                  <div className="text-2xl font-semibold text-ink-primary">{drilldown.metric.displayValue}</div>
                </div>
                <div>
                  <span className="text-ink-secondary">Period</span>
                  <div className="text-ink-primary">
                    {drilldown.metric.periodStart} to {drilldown.metric.periodEnd}
                  </div>
                </div>
                {drilldown.metric.previousValue !== null && drilldown.metric.previousValue !== undefined && (
                  <div>
                    <span className="text-ink-secondary">Prior month</span>
                    <div className="text-ink-primary">{drilldown.metric.previousValue}</div>
                  </div>
                )}
                {drilldown.metric.comparisonLabel && (
                  <div>
                    <span className="text-ink-secondary">Comparison</span>
                    <div className="text-ink-primary">{drilldown.metric.comparisonLabel}</div>
                  </div>
                )}
                <div>
                  <span className="text-ink-secondary">Polarity</span>
                  <div className="capitalize text-ink-primary">{drilldown.metric.polarity.replace(/_/g, " ")}</div>
                </div>
                <div>
                  <span className="text-ink-secondary">Status</span>
                  <div className="capitalize text-ink-primary">{drilldown.metric.status}</div>
                </div>
              </div>
            )}
            {drilldown.dimension && (
              <div className="space-y-4 text-sm">
                <div>
                  <span className="text-ink-secondary">Dimension</span>
                  <div className="text-ink-primary">{drilldown.dimension.name}</div>
                </div>
                <div>
                  <span className="text-ink-secondary">Value</span>
                  <div className="text-2xl font-semibold text-ink-primary">
                    {drilldown.dimension.value ?? "—"}
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
    </ProjectShell>
  );
}
