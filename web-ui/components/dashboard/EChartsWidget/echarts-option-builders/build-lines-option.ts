"use client";



import { useEffect, useMemo, useRef, useState } from "react";
import type { ChartClickEvent, ReferenceLineConfig, VisualizationOptions, WidgetConfig } from "../../types";
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
import { CanvasRenderer } from "echarts/renderers";import { formatNumber } from "../format-number";
import { signedPercent } from "../signed-percent";
import { percentChangeTooltipFormatter } from "../percent-change-tooltip-formatter";
import { getLegendConfig } from "../get-legend-config";
import { commonGrid } from "../common-grid";
import { axisColors } from "../axis-colors";
import { addAnalyticalLayers } from "../add-analytical-layers";
import { categorySeries } from "../category-series";
import { tooltipFormatter } from "../tooltip-formatter";
import { tooltipScatterFormatter } from "../tooltip-scatter-formatter";


export function buildLinesOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const { categories, values } = categorySeries(data, xKey, yKey);
  const colorsForChart = axisColors(isDark);
  const segments: number[][][] = [];
  for (let i = 0; i < values.length - 1; i++) {
    segments.push([[i, values[i]], [i + 1, values[i + 1]]]);
  }
  if (segments.length === 0) {
    return { title: { text: "Lines needs at least two points.", left: "center", top: "center", textStyle: { color: colorsForChart.text, fontSize: 12 } } };
  }
  return {
    backgroundColor: "transparent",
    tooltip: opts.showTooltip === false ? { show: false } : { trigger: "item" as const, formatter: (p: any) => `${xKey}: ${categories[p.value?.[0]?.[0] ?? 0]}<br/>${yKey}: ${formatNumber(Number(p.value?.[1] ?? 0), opts.yAxisFormat)}` },
    grid: { top: 30, right: 20, bottom: 60, left: 10, containLabel: true },
    xAxis: { type: "category" as const, data: categories, axisLabel: { rotate: categories.length > 8 ? -30 : 0, fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: { type: "value" as const, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: { lineStyle: { color: colorsForChart.grid } } },
    series: [{
      type: "lines" as const,
      coordinateSystem: "cartesian2d" as const,
      data: segments,
      lineStyle: { color: colors[0], curveness: 0.2, width: 2 },
      symbol: ["none", "arrow" as const],
      symbolSize: 6,
    }],
  };
}