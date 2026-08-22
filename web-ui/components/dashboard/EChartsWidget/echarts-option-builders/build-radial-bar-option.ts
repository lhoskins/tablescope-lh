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


export function buildRadialBarOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const inner = opts.innerRadius ?? 30;
  const outer = opts.outerRadius ?? 90;
  const start = opts.startAngle ?? 90;
  const end = opts.endAngle ?? -270;
  const max = opts.domainMax && opts.domainMax > 0 ? opts.domainMax : 100;
  const animate = !!opts.animate;
  const colorsForChart = axisColors(isDark);

  // Render each category as a gauge arc; multi-ring variant changes the radius.
  const rows = data.slice(0, 8).map((r, i) => ({
    name: String(r[xKey] ?? ""),
    value: toNumber(r[yKey]) ?? 0,
    color: colors[i % colors.length],
  }));

  const series = rows.map((r, i) => ({
    type: "gauge" as const,
    startAngle: start,
    endAngle: end,
    min: opts.domainMin ?? 0,
    max,
    radius: `${outer - i * ((outer - inner) / Math.max(rows.length, 1))}%`,
    center: ["50%", "50%"],
    axisLine: { lineStyle: { color: [[1, r.color]], width: 18 } },
    progress: { show: false },
    pointer: { show: true, width: 3, itemStyle: { color: r.color } },
    detail: { show: !!opts.showLabels, formatter: (v: number) => `${r.name}: ${formatNumber(v, opts.yAxisFormat, undefined, opts.currencySymbol)}`, fontSize: 10, color: colorsForChart.text, offsetCenter: ["0%", `${(i - rows.length / 2) * 20}%`] },
    data: [{ value: r.value, name: r.name }],
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: { show: false },
    title: { show: false },
    animation: animate,
  }));

  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", formatter: (p: any) => `${p.name}: ${formatNumber(Number(p.value ?? 0), opts.yAxisFormat, undefined, opts.currencySymbol)}` },
    series,
    animation: animate,
  };
}