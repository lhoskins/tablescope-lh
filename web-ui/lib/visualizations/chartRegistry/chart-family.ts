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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";


export type ChartFamily =
  | "kpi"
  | "table"
  | "line"
  | "area"
  | "bar"
  | "composed"
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