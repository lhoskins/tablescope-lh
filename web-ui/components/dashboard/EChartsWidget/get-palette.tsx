"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import type { ChartClickEvent, ReferenceLineConfig, VisualizationOptions, WidgetConfig } from "../types";
import { withDefaults } from "@/lib/visualizations/chartRegistry";
import {
  toNumber,
  preparePieData,
  prepareTreemapData,
  prepareFunnelData,
  prepareRadarData,
  prepareSankeyData,
  prepareWaterfallData,
  toPercentStacked,
  linearRegression,
  type Row,
} from "@/lib/visualizations/dataTransforms";
import * as echarts from "echarts/core";
import {
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  EffectScatterChart,
  RadarChart,
  TreemapChart,
  FunnelChart,
  SankeyChart,
  GaugeChart,
  HeatmapChart,
  SunburstChart,
  TreeChart,
  GraphChart,
  ParallelChart,
  LinesChart,
  CandlestickChart,
  BoxplotChart,
  PictorialBarChart,
  ThemeRiverChart,
  MapChart,
} from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  TitleComponent,
  AriaComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  PolarComponent,
  RadarComponent,
  GraphicComponent,
  VisualMapComponent,
  ParallelComponent,
  SingleAxisComponent,
  GeoComponent,
  DatasetComponent,
  TransformComponent,
} from "echarts/components";
import { LegacyGridContainLabel } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";import { BASE_COLORS } from "./base-colors";



export function getPalette(scheme: string | undefined, isDark: boolean): string[] {
  switch (scheme) {
    case "ocean":
      return ["#0ea5e9", "#06b6d4", "#14b8a6", "#3b82f6", "#6366f1", "#a855f7"];
    case "forest":
      return ["#22c55e", "#16a34a", "#15803d", "#84cc16", "#eab308", "#a16207"];
    case "warm":
      return ["#f97316", "#ef4444", "#f59e0b", "#db2777", "#8b5cf6", "#9333ea"];
    case "monochrome":
      return isDark
        ? ["#94a3b8", "#64748b", "#475569", "#334155", "#1e293b"]
        : ["#475569", "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0"];
    default:
      return BASE_COLORS;
  }
}