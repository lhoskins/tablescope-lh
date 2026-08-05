/**
 * Central chart registry.
 *
 * A single source of truth describing each chart family: the variants it
 * supports, the option fields the editor should expose, default option
 * values, the fields it requires, and the AI selection rules. The dashboard
 * widget editor, the option panel, config validation, and AI dashboard
 * generation all read from this registry so the chart catalog stays
 * consistent and easy to extend.
 */

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { ChartAlias } from "./chart-alias";



export const CHART_ALIASES: ChartAlias[] = [
  { alias: "line", label: "Line Chart", type: "line", variant: "" },
  { alias: "area", label: "Area Chart", type: "area", variant: "" },
  { alias: "stacked_area", label: "Stacked Area", type: "area", variant: "stacked_area", options: { stackMode: "stacked" } },
  { alias: "bar", label: "Bar Chart", type: "bar", variant: "column" },
  { alias: "horizontal_bar", label: "Horizontal Bar", type: "bar", variant: "horizontal_bar" },
  { alias: "stacked_bar", label: "Stacked Bar", type: "bar", variant: "stacked_bar", options: { stackMode: "stacked" } },
  { alias: "grouped_bar", label: "Grouped Bar", type: "bar", variant: "grouped_bar" },
  { alias: "combo", label: "Combo Chart", type: "combo", variant: "bar_line", options: { dualAxis: true } },
  { alias: "pie", label: "Pie Chart", type: "pie", variant: "" },
  { alias: "donut", label: "Donut Chart", type: "pie", variant: "donut", options: { innerRadius: 55 } },
  { alias: "scatter", label: "Scatter Chart", type: "scatter", variant: "" },
  { alias: "bubble", label: "Bubble Chart", type: "scatter", variant: "bubble", options: { bubble: true } },
  { alias: "radar", label: "Radar Chart", type: "radar", variant: "" },
  { alias: "radial_bar", label: "Radial Bar", type: "radial_bar", variant: "" },
  { alias: "treemap", label: "Treemap", type: "treemap", variant: "" },
  { alias: "funnel", label: "Funnel", type: "funnel", variant: "" },
  { alias: "sankey", label: "Sankey", type: "sankey", variant: "" },
  { alias: "heatmap", label: "Heatmap", type: "heatmap", variant: "" },
  { alias: "effect_scatter", label: "Effect Scatter", type: "effect_scatter", variant: "" },
  { alias: "gauge", label: "Gauge", type: "gauge", variant: "" },
  { alias: "sunburst", label: "Sunburst", type: "sunburst", variant: "" },
  { alias: "tree", label: "Tree", type: "tree", variant: "" },
  { alias: "graph", label: "Graph", type: "graph", variant: "" },
  { alias: "parallel", label: "Parallel Coordinates", type: "parallel", variant: "" },
  { alias: "lines", label: "Lines", type: "lines", variant: "" },
  { alias: "candlestick", label: "Candlestick", type: "candlestick", variant: "" },
  { alias: "boxplot", label: "Boxplot", type: "boxplot", variant: "" },
  { alias: "pictorial_bar", label: "Pictorial Bar", type: "pictorial_bar", variant: "" },
  { alias: "theme_river", label: "Theme River", type: "theme_river", variant: "" },
  { alias: "map", label: "Map", type: "map", variant: "" },
  { alias: "kpi", label: "KPI Card", type: "kpi", variant: "" },
  { alias: "table", label: "Table", type: "table", variant: "" },
];