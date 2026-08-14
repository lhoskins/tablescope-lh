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
  };
}
