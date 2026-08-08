"use client";


import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, ChartSubtype, WidgetFilter, ColumnInfo, VisualizationOptions, WidgetInteractions, WidgetClickAction, WidgetDateField } from "../types";
import type { QueryScope } from "@/types/query-scope";
import { WidgetRenderer } from "../WidgetRenderer";
import { ChartOptionsPanel } from "../ChartOptionsPanel";
import { getDefaultOptions, getChartDefinition } from "@/lib/visualizations/chartRegistry";import { ChartTypeDef } from "./chart-type-def";



export const CHART_TYPES: ChartTypeDef[] = [
  {
    type: "bar", label: "Bar", icon: "\u{1F4CA}",
    subtypes: [
      { value: "column", label: "Column" },
      { value: "stacked_bar", label: "Stacked" },
      { value: "grouped_bar", label: "Grouped" },
      { value: "horizontal_bar", label: "Horizontal" },
      { value: "stacked_horizontal", label: "Stacked Horiz." },
      { value: "positive_negative", label: "Pos / Neg" },
      { value: "waterfall", label: "Waterfall" },
      { value: "population_pyramid", label: "Pyramid" },
    ],
  },
  {
    type: "line", label: "Line", icon: "\u{1F4C8}",
    subtypes: [
      { value: "", label: "Straight" },
      { value: "smooth_line", label: "Smooth" },
      { value: "step_line", label: "Step" },
      { value: "dashed_line", label: "Dashed" },
      { value: "biaxial_line", label: "Biaxial" },
      { value: "tiny_line", label: "Tiny" },
      { value: "animated_line", label: "Animated" },
    ],
  },
  {
    type: "area", label: "Area", icon: "\u{1F4C9}",
    subtypes: [
      { value: "", label: "Area" },
      { value: "stacked_area", label: "Stacked" },
    ],
  },
  {
    type: "pie", label: "Pie", icon: "\u{1F369}",
    subtypes: [
      { value: "", label: "Pie" },
      { value: "donut", label: "Donut" },
      { value: "two_level", label: "Two-level" },
      { value: "gauge", label: "Gauge" },
    ],
  },
  {
    type: "combo", label: "Combo", icon: "\u{1F4CA}\u{1F4C8}",
    subtypes: [
      { value: "bar_line", label: "Bar + Line" },
      { value: "dual_line", label: "Dual Line" },
    ],
  },
  {
    type: "scatter", label: "Scatter", icon: "\u{1F4A0}",
    subtypes: [
      { value: "", label: "Scatter" },
      { value: "bubble", label: "Bubble" },
      { value: "best_fit", label: "Best fit" },
    ],
  },
  {
    type: "radar", label: "Radar", icon: "\u{1F578}\u{FE0F}",
    subtypes: [
      { value: "", label: "Radar" },
      { value: "scorecard", label: "Scorecard" },
    ],
  },
  {
    type: "radial_bar", label: "Radial", icon: "\u{1F3AF}",
    subtypes: [
      { value: "", label: "Radial Bar" },
      { value: "multi_ring", label: "Multi-ring" },
    ],
  },
  { type: "treemap", label: "Treemap", icon: "\u{1F9E9}", subtypes: [{ value: "", label: "Treemap" }, { value: "nested", label: "Nested" }] },
  { type: "funnel", label: "Funnel", icon: "\u{1FA9D}", subtypes: [{ value: "", label: "Funnel" }] },
  { type: "sankey", label: "Sankey", icon: "\u{1F500}", subtypes: [{ value: "", label: "Sankey" }] },
  { type: "kpi", label: "KPI", icon: "\u{1F522}", subtypes: [] },
  { type: "table", label: "Table", icon: "\u{1F4CB}", subtypes: [] },
];