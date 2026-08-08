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


export function buildParallelOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const colorsForChart = axisColors(isDark);
  const numericKeys: string[] = [];
  if (data.length) {
    Object.entries(data[0] as Record<string, unknown>).forEach(([k, v]) => {
      if (typeof v === "number" || (typeof v === "string" && !Number.isNaN(Number(v)))) numericKeys.push(k);
    });
  }
  if (numericKeys.length < 2) numericKeys.push(xKey, yKey);
  const schema = numericKeys.slice(0, 8).map((k) => ({ name: k, dim: k }));
  const parallelData = data.map((r) => schema.map((s) => toNumber(r[s.dim]) ?? 0));
  return {
    backgroundColor: "transparent",
    tooltip: opts.showTooltip === false ? { show: false } : { padding: 10, borderWidth: 1, trigger: "item" as const },
    parallelAxis: schema.map((s, i) => ({ dim: i, name: s.name, nameTextStyle: { color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, axisLabel: { color: colorsForChart.text, fontSize: 9 } })),
    parallel: { left: "5%", right: "13%", bottom: "10%", top: "20%", parallelAxisDefault: { axisLine: { lineStyle: { color: colorsForChart.line } }, axisLabel: { color: colorsForChart.text, fontSize: 9 } } },
    series: [{ type: "parallel" as const, lineStyle: { width: 2, color: colors[0] }, data: parallelData }],
  };
}