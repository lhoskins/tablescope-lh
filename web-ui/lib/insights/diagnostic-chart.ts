import type { InsightChart, InsightDiagnostic } from "@/lib/api/home-intelligence";
import type { VisualizationOptions } from "@/components/dashboard/types";

/**
 * Chart for one diagnostic step's evidence.
 *
 * Deliberately separate from `buildChart` (the conversational builder), which
 * ranks a bar chart by magnitude and caps it at 25 points. Those are the right
 * defaults for a chat answer and the wrong ones for evidence: applied to a
 * 31-period series they reorder the timeline by value and silently drop six
 * observations, so the reader sees a descending staircase with scrambled dates
 * rather than the trend the method actually measured.
 *
 * Here the row order *is* the finding — the projection is already `ORDER BY`
 * period — so rows are passed through untouched and every observation is kept.
 */

const CHART_TYPES = new Set<InsightChart["type"]>([
  "bar", "line", "area", "pie", "combo", "scatter", "boxplot", "heatmap",
]);

/** Analytical layer name (from the intent) → renderer option. */
const LAYER_OPTIONS: Record<string, keyof VisualizationOptions> = {
  regression_line: "showRegressionLine",
  confidence_band: "confidenceBand",
  prediction_band: "confidenceBand",
  change_point: "showChangePoint",
};

export interface DiagnosticChart {
  chart: InsightChart;
  options: Partial<VisualizationOptions>;
  /** 0-based positions the method flagged, for the evidence table. */
  anomalyRows: number[];
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function buildDiagnosticChart(step: InsightDiagnostic): DiagnosticChart | null {
  const columns = step.result?.columns ?? [];
  const rows = (step.result?.rows ?? []) as Record<string, unknown>[];
  if (!columns.length || !rows.length) return null;

  // An intent with no chart family (or an explicit `table`) is evidence best
  // read as rows — forcing it into a chart would misrepresent it.
  const family = step.presentation?.chart;
  if (!family || family === "table") return null;
  const type = CHART_TYPES.has(family as InsightChart["type"])
    ? (family as InsightChart["type"])
    : "line";

  // Roles come from the projection that produced these rows; position is only
  // a fallback for older cached diagnostics that predate them.
  const xField = step.roles?.x ?? columns[0];
  const yField = step.roles?.y ?? columns[1] ?? columns[0];
  const y2Field = step.roles?.y2;

  const series = rows.map((r) => {
    const point: { label: string; value: number; value2?: number } = {
      label: String(r[xField] ?? ""),
      value: toNumber(r[yField]) ?? 0,
    };
    if (y2Field) {
      const second = toNumber(r[y2Field]);
      if (second !== null) point.value2 = second;
    }
    return point;
  });
  if (!series.length) return null;

  const options: Partial<VisualizationOptions> = { showLegend: false, showGrid: false };
  for (const layer of step.presentation?.layers ?? []) {
    const key = LAYER_OPTIONS[layer];
    if (key) (options as Record<string, unknown>)[key] = true;
  }

  // The method's own flags, not the renderer's 2-sigma re-derivation: R fits an
  // ETS model, so a point within 2 sigma of the mean can still fall outside its
  // expected band. Marking a point the method did not flag would contradict the
  // finding printed directly above the chart.
  const anomalyRows = (step.markers?.anomalyIndices ?? []).filter(
    (i) => Number.isInteger(i) && i >= 0 && i < series.length,
  );
  if (anomalyRows.length) options.markedIndices = anomalyRows;
  const changePoint = step.markers?.changePointIndex;
  if (typeof changePoint === "number" && changePoint >= 0 && changePoint < series.length) {
    options.markedChangePointIndex = changePoint;
  }

  return {
    chart: {
      type,
      data: { series },
      roles: { x: xField, y: yField, ...(y2Field ? { y2: y2Field } : {}) },
      seriesLabels: { value: yField, ...(y2Field ? { value2: y2Field } : {}) },
    },
    options,
    anomalyRows,
  };
}
