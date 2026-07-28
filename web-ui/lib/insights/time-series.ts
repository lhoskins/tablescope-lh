"use client";

import type { InsightCard } from "@/lib/api/home-intelligence";

export type TimeSeriesInterval = "day" | "week" | "month" | "year";
export type TimeSeriesRange = "7d" | "30d" | "90d" | "1y" | "2y";

export const INTERVAL_OPTIONS: { value: TimeSeriesInterval; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

export const RANGE_OPTIONS: { value: TimeSeriesRange; label: string }[] = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "90d", label: "90D" },
  { value: "1y", label: "1Y" },
  { value: "2y", label: "2Y" },
];

const _ISO_LIKE_RE =
  /^\d{4}(-\d{2})?(-\d{2})?(-W\d{2})?$/;

export function parseDateLabel(label: unknown): string | null {
  const s = String(label ?? "").trim();
  if (_ISO_LIKE_RE.test(s) || /^\d{4}$/.test(s)) {
    return s;
  }
  return null;
}

export function isTimeSeriesEligible(card: InsightCard): boolean {
  const chart = card.chart;
  if (!chart) return false;
  const type = chart.type;
  if (!["line", "area", "bar"].includes(type)) return false;
  const series = chart.data?.series;
  if (!series || series.length === 0) {
    const rows = chart.data?.rows;
    if (!rows || rows.length === 0) return false;
    return rows.some((r) =>
      parseDateLabel(r[chart.roles?.x ?? ""] ?? r["label"]),
    );
  }
  return series.some((s) => parseDateLabel(s.label));
}

export function inferDefaultInterval(card: InsightCard): TimeSeriesInterval {
  if (card.timeSeriesView?.interval) return card.timeSeriesView.interval;
  const series = card.chart?.data?.series ?? [];
  const first = String(series[0]?.label ?? "");
  if (/^\d{4}-W\d{2}$/.test(first)) return "week";
  if (/^\d{4}-\d{2}-\d{2}$/.test(first)) return "day";
  if (/^\d{4}-\d{2}$/.test(first) || /^\d{4}-Q\d$/.test(first)) return "month";
  if (/^\d{4}$/.test(first)) return "year";
  return "month";
}

export function clampInterval(
  interval: TimeSeriesInterval,
  supported: string[] | undefined,
): TimeSeriesInterval {
  if (!supported || supported.length === 0) return interval;
  if (supported.includes(interval)) return interval;
  const order: TimeSeriesInterval[] = ["day", "week", "month", "year"];
  const candidates = order.filter((i) => supported.includes(i));
  return candidates[candidates.length - 1] ?? (supported[0] as TimeSeriesInterval);
}

export function formatPercentChange(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "N/A";
  const pct = ratio * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}
