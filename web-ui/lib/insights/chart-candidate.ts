import type {
  InsightChart,
  VizCandidate,
} from "@/lib/api/home-intelligence";

/** Apply both the visual family and its candidate-specific field mappings. */
export function applyCandidateToInsightChart(
  baseChart: InsightChart,
  candidate: VizCandidate,
): InsightChart {
  const decision = candidate.decision;
  const roles = { ...(baseChart.roles ?? {}) };

  if (decision.xField) roles.x = decision.xField;

  switch (decision.chartType) {
    case "heatmap":
      // Matrix heatmap: x + second dimension + value. Calendar heatmap only
      // needs date + value and deliberately has no group axis.
      if (decision.yField) roles.value = decision.yField;
      if (decision.chartStyle === "calendar") {
        delete roles.group;
        delete roles.y2;
      } else if (decision.y2Field) {
        roles.group = decision.y2Field;
        roles.y = decision.y2Field;
      }
      break;
    case "sankey":
    case "graph":
    case "tree":
    case "lines":
      if (decision.yField) roles.group = decision.yField;
      if (decision.y2Field) roles.value = decision.y2Field;
      break;
    case "treemap":
    case "sunburst":
      if (decision.yField) roles.value = decision.yField;
      if (decision.y2Field) roles.group = decision.y2Field;
      break;
    default:
      if (decision.yField) {
        roles.y = decision.yField;
        roles.value = decision.yField;
      }
      if (decision.y2Field) roles.y2 = decision.y2Field;
  }

  return {
    ...baseChart,
    type: decision.chartType as InsightChart["type"],
    subtype: decision.chartStyle || undefined,
    roles,
  };
}

/** Reconstruct the result shape used by the server-side compatibility ranker. */
export function insightChartCandidateData(chart: InsightChart): {
  columns: string[];
  rows: Record<string, unknown>[];
} {
  if (chart.data.rows?.length) {
    return {
      columns:
        chart.data.columns?.length
          ? chart.data.columns
          : Object.keys(chart.data.rows[0] ?? {}),
      rows: chart.data.rows,
    };
  }

  const series = chart.data.series ?? [];
  if (series.length === 0) return { columns: [], rows: [] };
  const xField = chart.roles?.x ?? "label";
  const yField = chart.seriesLabels?.value ?? chart.roles?.y ?? chart.roles?.value ?? "value";
  const y2Field = chart.seriesLabels?.value2 ?? chart.roles?.y2;
  const hasY2 = Boolean(y2Field && series.some((point) => point.value2 != null));
  const rows = series.map((point) => ({
    [xField]: point.label,
    [yField]: point.value,
    ...(hasY2 && y2Field ? { [y2Field]: point.value2 } : {}),
  }));
  return {
    columns: [xField, yField, ...(hasY2 && y2Field ? [y2Field] : [])],
    rows,
  };
}
