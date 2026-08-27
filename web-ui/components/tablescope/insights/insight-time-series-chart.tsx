"use client";

import { useEffect, useMemo, useState } from "react";
import {
  InsightChartView,
  OperationalInsightChartView,
} from "@/components/tablescope/home/intelligence-card";
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
import {
  clampInterval,
  inferDefaultInterval,
  isTimeSeriesEligible,
} from "@/lib/insights/time-series";
import { IconChevronRight, IconChevronDown } from "@tabler/icons-react";

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
    // A period's percent-change is null whenever the comparison is
    // mathematically undefined (a zero-count prior period, a missing prior
    // period, or an in-progress partial period) -- not when the underlying
    // metric has no observation. That's common for sparse/anomaly-count
    // metrics, where most periods sit at zero: with nulls left disconnected
    // the line renders as a scatter of isolated, unconnected dots instead
    // of a readable trend. Interpolate through those points instead so the
    // trend stays visually continuous; the tooltip still shows the real
    // current/previous values for every point, undefined or not.
    connectNulls: true,
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
  presentation?: "default" | "operational";
}

export function InsightTimeSeriesChart({
  card,
  projectId,
  height,
  onViewChange,
  presentation = "default",
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

  const ChartView =
    presentation === "operational" && mode === "value"
      ? OperationalInsightChartView
      : InsightChartView;

  if (!eligible || !card.chart) {
    if (!card.chart) return null;
    return <ChartView chart={card.chart} height={height} />;
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
        <ChartView chart={chart} options={options} height={height} />
      ) : (
        <ChartView chart={card.chart} height={height} />
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
