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


export function buildBoxplotOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const colorsForChart = axisColors(isDark);
  const source: (string | number)[][] = [[xKey, yKey]];
  const valid = data.filter((r) => toNumber(r[yKey]) !== null);
  if (valid.length === 0) {
    return { title: { text: "Boxplot needs numeric values for the Y column.", left: "center", top: "center", textStyle: { color: colorsForChart.text, fontSize: 12 } } };
  }
  for (const r of valid) source.push([String(r[xKey] ?? ""), toNumber(r[yKey]) ?? 0]);
  const categories = Array.from(new Set(source.slice(1).map((r) => String(r[0]))));
  return {
    backgroundColor: "transparent",
    tooltip: opts.showTooltip === false ? { show: false } : { trigger: "item" as const },
    dataset: [{ source }, { type: "boxplot" as const }],
    xAxis: { type: "category" as const, data: categories, axisLabel: { fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: { type: "value" as const, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: { lineStyle: { color: colorsForChart.grid } } },
    series: [{ type: "boxplot" as const, datasetIndex: 1, itemStyle: { color: colors[0], borderColor: colorsForChart.text } }],
  };
}