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
import { CanvasRenderer } from "echarts/renderers";


// ── Exotic ECharts families (sunburst, tree, graph, parallel, lines,
//    candlestick, boxplot, pictorial bar, theme river, map). These builders
//    produce best-effort options from the generic x/y/group columns; a chart
//    with no suitable data shape shows a friendly title instead of crashing.

export function categorySeries<T extends Row>(rows: T[], xKey: string, yKey: string) {
  const order: string[] = [];
  const map = new Map<string, number>();
  for (const r of rows) {
    const label = String(r[xKey] ?? "");
    const v = toNumber(r[yKey]) ?? 0;
    if (!map.has(label)) {
      order.push(label);
      map.set(label, 0);
    }
    map.set(label, (map.get(label) || 0) + v);
  }
  return { categories: order, values: order.map((c) => map.get(c) ?? 0) };
}