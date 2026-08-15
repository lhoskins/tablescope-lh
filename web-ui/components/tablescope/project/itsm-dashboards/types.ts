"use client";

export interface ItsmMetricValue {
  metricKey: string;
  label: string;
  value: number | null;
  displayValue: string;
  periodStart: string;
  periodEnd: string;
  previousValue: number | null;
  delta: number | null;
  deltaPercent: number | null;
  direction: "up" | "down" | "flat" | null;
  polarity: "higher_is_better" | "lower_is_better" | "neutral";
  outcome: "favorable" | "unfavorable" | "neutral" | null;
  comparisonLabel: string | null;
  status: "measured" | "calculated" | "proxy" | "not_implemented";
  asOf: string | null;
  unit: string | null;
  description: string | null;
  calculation: string | null;
  target: number | null;
}

export interface ItsmChartSeries {
  name: string;
  x: string[];
  y: (number | null)[];
}

export interface ItsmChart {
  chartKey: string;
  title: string;
  chartType: string;
  xAxisLabel: string | null;
  yAxisLabel: string | null;
  series: ItsmChartSeries[];
  categories: string[];
  unit: string | null;
}

export interface ItsmDashboardResult {
  dashboard: string;
  asOf: string;
  filters: Record<string, unknown>;
  metrics: ItsmMetricValue[];
  charts: ItsmChart[];
  dataQuality: {
    latestCompleteMonth: string;
    missingMetrics: string[];
    warnings: string[];
    cacheStatus?: "fresh" | "stale" | "miss" | "refreshed";
    cacheAgeSeconds?: number;
  };
}

export interface ItsmDrilldownContributor {
  name: string;
  value: number | null;
  display_value: string;
  share_percent: number | null;
}

export interface ItsmDrilldownRecord {
  record_id: string;
  priority: string | null;
  site: string | null;
  category: string | null;
  value: number | null;
  display_value: string | null;
}

export interface ItsmMetricDrilldown {
  metric_key: string;
  label: string;
  description: string;
  calculation: string;
  unit: string | null;
  period_start: string;
  period_end: string;
  contributors_label: string;
  contributors: ItsmDrilldownContributor[];
  majority_share_percent: number | null;
  records: ItsmDrilldownRecord[];
  warnings: string[];
}

export type ItsmCardSize = "compact" | "standard" | "wide";

export interface ItsmDashboardLayout {
  order: string[];
  sizes: Record<string, ItsmCardSize>;
}
