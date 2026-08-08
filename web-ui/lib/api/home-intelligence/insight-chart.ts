"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightChart {
  /**
   * Chart family. ``kpi_grid`` uses the lightweight tile renderer; every other
   * value maps onto the dashboard's WidgetRenderer catalog so Intelligence
   * cards render with the exact same charts as dashboards.
   */
  type:
    | "kpi_grid"
    | "bar"
    | "line"
    | "area"
    | "pie"
    | "combo"
    | "scatter"
    | "effect_scatter"
    | "radar"
    | "radial_bar"
    | "treemap"
    | "funnel"
    | "sankey"
    | "heatmap"
    | "gauge"
    | "sunburst"
    | "tree"
    | "graph"
    | "parallel"
    | "lines"
    | "candlestick"
    | "boxplot"
    | "pictorial_bar"
    | "theme_river"
    | "map";
  /** Dashboard chart subtype (e.g. "donut", "smooth_line", "waterfall"). */
  subtype?: string;
  title?: string;
  data: {
    /**
     * Each point carries a `value`; two-metric charts (combo/scatter/bubble)
     * also carry `value2` for the second axis/size.
     */
    series?: { label: string; value: number; value2?: number }[];
    /**
     * Generic data rows for multi-dimensional charts (heatmap, radar,
     * treemap, sankey, funnel). When present, `columns` lists the field names.
     */
    rows?: Record<string, unknown>[];
    columns?: string[];
    threshold?: number;
    kpis?: { value: string; label: string; delta?: string }[];
  };
  /**
   * Axis/field roles for the renderer. `x` is the primary dimension (or first
   * measure for scatter), `y` the value, `y2` the second measure, `group` a
   * second dimension (heatmap Y, treemap child, sankey target, radar metric).
   */
  roles?: { x?: string; y?: string; y2?: string; z?: string; group?: string; value?: string };
  /** Human-readable column names per series field, for axis/legend labels. */
  seriesLabels?: { value?: string; value2?: string };
}