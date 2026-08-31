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
import { CanvasRenderer } from "echarts/renderers";import { formatFullPrecision, type ValueScale } from "./format-number";



/**
 * `scale` is accepted for call-site compatibility with `formatNumber` but is
 * intentionally unused: a tooltip always shows the exact value (commas,
 * two decimals) regardless of any K/M scale applied to the same value's
 * axis tick or bar label -- hovering is how a user checks the real number.
 */
export function tooltipFormatter(params: any, format?: string, _scale?: ValueScale, currencySymbol?: string) {
  const rows = Array.isArray(params) ? params : [params];
  if (!rows.length) return "";
  const axis = rows[0].axisValueLabel ?? rows[0].name ?? "";
  return axis + rows.map((p: any) => `<br/>${p.marker} ${p.seriesName}: ${formatFullPrecision(Number(p.value ?? 0), format, currencySymbol)}`).join("");
}