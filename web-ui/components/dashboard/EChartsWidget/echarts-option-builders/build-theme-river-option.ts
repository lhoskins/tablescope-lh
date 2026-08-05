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


export function buildThemeRiverOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const groupKey = widget.groupByColumn || "";
  const colorsForChart = axisColors(isDark);
  const categories = Array.from(new Set(data.map((r) => String(r[xKey] ?? ""))));
  const riverData: [string | number, number, string][] = data.map((r) => [String(r[xKey] ?? ""), toNumber(r[yKey]) ?? 0, groupKey ? String(r[groupKey] ?? "") : yKey]);
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" as const, axisPointer: { type: "line" as const, lineStyle: { color: "rgba(0,0,0,0.2)", width: 1, type: "solid" as const } } },
    singleAxis: { top: 50, bottom: 50, axisTick: {}, axisLabel: { fontSize: 10, color: colorsForChart.text }, type: "category" as const, data: categories, axisPointer: { animation: true, label: { show: true, fontSize: 10 } }, splitLine: { show: true, lineStyle: { type: "dashed" as const, opacity: 0.2 } } },
    series: [{
      type: "themeRiver" as const,
      emphasis: { itemStyle: { shadowBlur: 20, shadowColor: "rgba(0, 0, 0, 0.8)" } },
      data: riverData,
      color: colors,
    }],
  };
}