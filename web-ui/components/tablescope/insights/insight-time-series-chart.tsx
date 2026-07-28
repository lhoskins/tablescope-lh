"use client";

import { useEffect, useMemo, useState } from "react";
import { InsightChartView } from "@/components/tablescope/home/intelligence-card";
import type { VisualizationOptions } from "@/components/dashboard/types";
import type { InsightChart } from "@/lib/api/home-intelligence";
import {
  useInsightTimeSeries,
} from "@/lib/hooks/use-insight-time-series";
import { TimeSeriesViewControls } from "./time-series-view-controls";
import type {
  InsightCard,
  TimeSeriesCalculation,
  TimeSeriesInterval,
  TimeSeriesRange,
  TimeSeriesResponse,
  TimeSeriesViewMode,
  TimeSeriesViewState,
} from "@/lib/api/home-intelligence";
import { IconChevronRight, IconChevronDown } from "@tabler/icons-react";

function parseDateLabel(label: unknown): string | null {
  const s = String(label ?? "").trim();
  if (/^\d{4}(-\d{2})?(-\d{2})?(-W\d{2})?$/.test(s) || /^\d{4}$/.test(s)) {
    return s;
  }
  return null;
}

function isTimeSeriesEligible(card: InsightCard): boolean {
  const chart = card.chart;
  if (!chart) return false;
  const type = chart.type;
  if (!["line", "area", "bar"].includes(type)) return false;
  const series = chart.data?.series;
  if (!series || series.length === 0) {
    const rows = chart.data?.rows;
    if (!rows || rows.length === 0) return false;
    return rows.some((r) => parseDateLabel(r[chart.roles?.x ?? ""] ?? r["label"]));
  }
  return series.some((s) => parseDateLabel(s.label));
}

function inferDefaultInterval(card: InsightCard): TimeSeriesInterval {
  if (card.timeSeriesView?.interval) return card.timeSeriesView.interval;
  const series = card.chart?.data?.series ?? [];
  const first = String(series[0]?.label ?? "");
  if (/^\d{4}-W\d{2}$/.test(first)) return "week";
  if (/^\d{4}-\d{2}-\d{2}$/.test(first)) return "day";
  if (/^\d{4}-\d{2}$/.test(first) || /^\d{4}-Q\d$/.test(first)) return "month";
  if (/^\d{4}$/.test(first)) return "year";
  return "month";
}

function clampInterval(
  interval: TimeSeriesInterval,
  supported: string[] | undefined,
): TimeSeriesInterval {
  if (!supported || supported.length === 0) return interval;
  if (supported.includes(interval)) return interval;
  const order: TimeSeriesInterval[] = ["day", "week", "month", "year"];
  const candidates = order.filter((i) => supported.includes(i));
  return candidates[candidates.length - 1] ?? (supported[0] as TimeSeriesInterval);
}

function buildValueChart(
  card: InsightCard,
  response: TimeSeriesResponse,
): InsightChart {
  const originalType = card.chart?.type ?? "line";
  const originalSubtype = card.chart?.subtype;
  const type = ["line", "area", "bar"].includes(originalType) ? originalType : "line";
  const metricName = response.metric.name;
  const rows = response.points
    .filter((p) => p.current_value !== null)
    .map((p) => ({
      period: p.label,
      value: p.current_value,
    }));
  return {
    type,
    subtype: type === originalType ? originalSubtype : undefined,
    title: card.chart?.title,
    data: {
      rows,
      columns: ["period", "value"],
    },
    roles: { x: "period", value: "value" },
    seriesLabels: { value: metricName },
  } as InsightChart;
}

function buildPercentChangeChart(
  response: TimeSeriesResponse,
): InsightChart {
  const metricName = response.metric.name;
  const rows = response.points.map((p) => ({
    period: p.label,
    value: p.percent_change_ratio,
    currentValue: p.current_value,
    previousValue: p.previous_value,
  }));
  return {
    type: "line",
    title: response.comparison_label,
    data: {
      rows,
      columns: ["period", "value", "currentValue", "previousValue"],
    },
    roles: { x: "period", value: "value" },
    seriesLabels: { value: `% change in ${metricName}` },
  } as InsightChart;
}

function percentChangeOptions(
  response: TimeSeriesResponse,
): Partial<VisualizationOptions> {
  return {
    yAxisFormat: "percent",
    signedPercentAxis: true,
    referenceLines: [{ axis: "y", value: 0, label: "Zero baseline" }],
    colorBySign: true,
    showDots: true,
    percentChangeTooltip: true,
    showGrid: true,
    lineStyle: "solid",
    curveType: "linear",
    connectNulls: false,
  };
}

function CalculationSummary({
  calculation,
}: {
  calculation: TimeSeriesCalculation;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-line-tertiary bg-bg-secondary/50 p-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 text-[11px] font-medium text-ink-secondary"
        aria-expanded={open}
      >
        {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
        Calculation details
      </button>
      {open && (
        <div className="mt-2 space-y-1 text-[11px] text-ink-tertiary">
          <p>
            <span className="font-medium">Formula:</span> {calculation.formula}
          </p>
          <p>
            <span className="font-medium">Interval:</span> {calculation.interval} ·{" "}
            <span className="font-medium">Range:</span> {calculation.range} {" "}
            {calculation.as_of && `(as of ${calculation.as_of})`}
          </p>
          {calculation.notes.map((note, i) => (
            <p key={i}>{note}</p>
          ))}
        </div>
      )}
    </div>
  );
}

export interface InsightTimeSeriesChartProps {
  card: InsightCard;
  projectId: number;
  height?: number;
  onViewChange?: (view: TimeSeriesViewState) => void;
}

export function InsightTimeSeriesChart({
  card,
  projectId,
  height,
  onViewChange,
}: InsightTimeSeriesChartProps) {
  const eligible = useMemo(() => isTimeSeriesEligible(card), [card]);
  const initialInterval = useMemo(
    () => inferDefaultInterval(card),
    [card],
  );

  const [mode, setMode] = useState<TimeSeriesViewMode>(
    card.timeSeriesView?.mode ?? "value",
  );
  const [interval, setInterval] = useState<TimeSeriesInterval>(initialInterval);
  const [range, setRange] = useState<TimeSeriesRange>(
    card.timeSeriesView?.range ?? "1y",
  );

  const { data: response, isLoading } = useInsightTimeSeries(
    eligible ? card.insightId ?? card.id : undefined,
    projectId,
    interval,
    range,
    eligible,
  );

  const supportedIntervals: string[] | undefined =
    response?.supported_intervals ??
    (response?.source_grain ? [response.source_grain] : undefined);
  const effectiveInterval = clampInterval(interval, supportedIntervals);

  useEffect(() => {
    if (effectiveInterval !== interval) {
      setInterval(effectiveInterval);
    }
  }, [effectiveInterval, interval]);

  useEffect(() => {
    if (!eligible) return;
    onViewChange?.({ mode, interval: effectiveInterval, range });
  }, [eligible, mode, effectiveInterval, range, onViewChange]);

  const chart = useMemo<InsightChart | null>(() => {
    if (!response || !eligible) return null;
    if (mode === "value") {
      return buildValueChart(card, response);
    }
    return buildPercentChangeChart(response);
  }, [response, eligible, card, mode]);

  const options: Partial<VisualizationOptions> | undefined = useMemo(() => {
    if (mode === "percent_change" && response) {
      return percentChangeOptions(response);
    }
    return undefined;
  }, [mode, response]);

  if (!eligible || !card.chart) {
    if (!card.chart) return null;
    return <InsightChartView chart={card.chart} height={height} />;
  }

  return (
    <div className="space-y-2">
      <TimeSeriesViewControls
        mode={mode}
        interval={effectiveInterval}
        range={range}
        supportedIntervals={
          supportedIntervals as TimeSeriesInterval[] | undefined
        }
        comparisonLabel={
          mode === "percent_change" ? response?.comparison_label : undefined
        }
        loading={isLoading}
        onModeChange={setMode}
        onIntervalChange={setInterval}
        onRangeChange={setRange}
      />
      {chart ? (
        <InsightChartView chart={chart} options={options} height={height} />
      ) : (
        <InsightChartView chart={card.chart} height={height} />
      )}
      {mode === "percent_change" && response?.calculation && (
        <CalculationSummary calculation={response.calculation} />
      )}
      {response?.warnings && response.warnings.length > 0 && (
        <div className="text-[11px] text-warning" role="alert">
          {response.warnings.join(" ")}
        </div>
      )}
    </div>
  );
}
