/**
 * ECharts capability registry — single source of truth for every governed chart
 * family. The renderer imports the series/components listed here, the selector
 * reads the fit rules/scores, and the editor reads options/variants.
 *
 * This file is the lockstep contract: a family is selectable only when
 * `enabled` is true and the renderer has a builder for it.
 */

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";

export type EChartFamily =
  | "kpi"
  | "table"
  | "line"
  | "area"
  | "bar"
  | "combo"
  | "pie"
  | "scatter"
  | "effect_scatter"
  | "radar"
  | "radial_bar"
  | "treemap"
  | "sunburst"
  | "tree"
  | "funnel"
  | "sankey"
  | "graph"
  | "parallel"
  | "lines"
  | "heatmap"
  | "candlestick"
  | "boxplot"
  | "pictorial_bar"
  | "theme_river"
  | "gauge"
  | "map";

export interface EChartFamilyDefinition {
  /** Renderer key (must match WidgetType). */
  family: EChartFamily;
  /** ECharts series type. */
  seriesType: string;
  /** Required echarts/components in addition to the common set. */
  components: string[];
  /** Human label. */
  label: string;
  /** Whether the planner may select this family. */
  enabled: boolean;
  /** Gated families need explicit opt-in (e.g. geo maps). */
  gated: boolean;
  /** Reason for gating / disabled state. */
  reason?: string;
  /** Required data shapes for the family. */
  fits: Array<"time" | "category" | "numeric" | "matrix" | "hierarchy" | "flow" | "distribution" | "ohlc" | "single">;
  /** Default visualization options for the family. */
  defaultOptions?: Partial<VisualizationOptions>;
}

export const ECHART_FAMILIES: EChartFamilyDefinition[] = [
  { family: "kpi", seriesType: "custom", components: [], label: "KPI Card", enabled: true, gated: false, fits: ["single"], defaultOptions: {} },
  { family: "table", seriesType: "custom", components: [], label: "Table", enabled: true, gated: false, fits: [] },
  { family: "line", seriesType: "line", components: [], label: "Line", enabled: true, gated: false, fits: ["time", "category", "numeric"] },
  { family: "area", seriesType: "line", components: [], label: "Area", enabled: true, gated: false, fits: ["time", "category", "numeric"] },
  { family: "bar", seriesType: "bar", components: [], label: "Bar", enabled: true, gated: false, fits: ["category", "numeric"] },
  { family: "combo", seriesType: "line", components: [], label: "Combo", enabled: true, gated: false, fits: ["time", "category", "numeric"] },
  { family: "pie", seriesType: "pie", components: [], label: "Pie / Donut", enabled: true, gated: false, fits: ["category", "numeric"] },
  { family: "scatter", seriesType: "scatter", components: [], label: "Scatter / Bubble", enabled: true, gated: false, fits: ["numeric"] },
  { family: "effect_scatter", seriesType: "effectScatter", components: [], label: "Effect Scatter", enabled: true, gated: false, fits: ["numeric", "time"], defaultOptions: { showDots: true } },
  { family: "radar", seriesType: "radar", components: ["RadarComponent"], label: "Radar", enabled: true, gated: false, fits: ["category", "numeric"] },
  { family: "radial_bar", seriesType: "bar", components: ["PolarComponent"], label: "Radial Bar", enabled: true, gated: false, fits: ["category", "numeric"] },
  { family: "treemap", seriesType: "treemap", components: [], label: "Treemap", enabled: true, gated: false, fits: ["hierarchy", "category", "numeric"] },
  { family: "sunburst", seriesType: "sunburst", components: [], label: "Sunburst", enabled: false, gated: false, fits: ["hierarchy", "category", "numeric"], reason: "Renderer builder not yet available." },
  { family: "tree", seriesType: "tree", components: [], label: "Tree", enabled: false, gated: false, fits: ["hierarchy", "category", "numeric"], reason: "Renderer builder not yet available." },
  { family: "funnel", seriesType: "funnel", components: [], label: "Funnel", enabled: true, gated: false, fits: ["category", "numeric"] },
  { family: "sankey", seriesType: "sankey", components: [], label: "Sankey", enabled: true, gated: false, fits: ["flow", "category", "numeric"] },
  { family: "graph", seriesType: "graph", components: [], label: "Graph", enabled: false, gated: false, fits: ["flow", "numeric"], reason: "Renderer builder not yet available." },
  { family: "parallel", seriesType: "parallel", components: ["ParallelComponent"], label: "Parallel", enabled: false, gated: false, fits: ["numeric"], reason: "Renderer builder not yet available." },
  { family: "lines", seriesType: "lines", components: [], label: "Lines", enabled: false, gated: false, fits: ["flow"], reason: "Renderer builder not yet available." },
  { family: "heatmap", seriesType: "heatmap", components: ["VisualMapComponent"], label: "Heatmap", enabled: false, gated: false, fits: ["matrix", "category", "numeric"], reason: "Renderer builder not yet available." },
  { family: "candlestick", seriesType: "candlestick", components: [], label: "Candlestick", enabled: false, gated: false, fits: ["ohlc", "time"], reason: "Renderer builder not yet available." },
  { family: "boxplot", seriesType: "boxplot", components: [], label: "Boxplot", enabled: false, gated: false, fits: ["distribution", "category", "numeric"], reason: "Renderer builder not yet available." },
  { family: "pictorial_bar", seriesType: "pictorialBar", components: [], label: "Pictorial Bar", enabled: false, gated: false, fits: ["category", "numeric"], reason: "Renderer builder not yet available." },
  { family: "theme_river", seriesType: "themeRiver", components: ["SingleAxisComponent"], label: "Theme River", enabled: false, gated: false, fits: ["time", "category", "numeric"], reason: "Renderer builder not yet available." },
  { family: "gauge", seriesType: "gauge", components: [], label: "Gauge", enabled: true, gated: false, fits: ["single", "numeric"] },
  { family: "map", seriesType: "map", components: [], label: "Map", enabled: false, gated: true, fits: ["category", "numeric"], reason: "Requires approved basemap data and licensing." },
];

export const ENABLED_ECHART_FAMILIES = ECHART_FAMILIES.filter((f) => f.enabled);

export function isEChartFamilyEnabled(family: string): boolean {
  return ECHART_FAMILIES.some((f) => f.family === family && f.enabled);
}

export function getEChartFamily(family: string): EChartFamilyDefinition | undefined {
  return ECHART_FAMILIES.find((f) => f.family === family);
}

/** Families that map to a real WidgetType. */
export const ECHART_WIDGET_FAMILIES = new Set<EChartFamily>([
  "kpi",
  "table",
  "line",
  "area",
  "bar",
  "combo",
  "pie",
  "scatter",
  "effect_scatter",
  "radar",
  "radial_bar",
  "treemap",
  "funnel",
  "sankey",
  "gauge",
]);
