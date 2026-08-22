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
import { tooltipScatterFormatter } from "../tooltip-scatter-formatter";import { buildReferenceLines } from "./build-reference-lines";
import { axisScaleLabel, formatAxisNumber } from "../axis-scale";



export function buildComboOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  y2Key: string,
  chartData: Row[],
  seriesNames: string[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const sub = widget.chartSubtype ?? "";
  const showGrid = !tiny && opts.showGrid !== false;
  const showLegend = !tiny && opts.showLegend !== false;
  const colorsForChart = axisColors(isDark);
  const dualAxis = opts.dualAxis !== false;
  const animate = !!opts.animate;

  const categoryData = chartData.map((r) => String(r[xKey] ?? ""));
  const series: any[] = [];

  if (seriesNames.length >= 2 && (sub === "bar_line" || sub === "dual_line")) {
    // First series as bars, second as line
    const barName = seriesNames[0];
    const lineName = seriesNames[1];
    series.push({
      name: barName,
      type: "bar" as const,
      data: chartData.map((r) => toNumber(r[barName]) ?? 0),
      itemStyle: { color: colors[0] },
      label: { show: !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat, opts.valueScale) },
      yAxisIndex: 0,
      barMaxWidth: 40,
      animation: animate,
    });
    series.push({
      name: lineName,
      type: "line" as const,
      smooth: opts.curveType === "monotone",
      data: chartData.map((r) => toNumber(r[lineName]) ?? 0),
      itemStyle: { color: colors[1 % colors.length] },
      yAxisIndex: dualAxis ? 1 : 0,
      label: { show: !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat, opts.valueScale) },
      animation: animate,
    });
  } else if (y2Key) {
    series.push({
      name: yKey,
      type: "bar" as const,
      data: chartData.map((r) => toNumber(r[yKey]) ?? 0),
      itemStyle: { color: colors[0] },
      yAxisIndex: 0,
      barMaxWidth: 40,
      animation: animate,
    });
    const y2Values = chartData.map((r) => toNumber(r[y2Key]));
    if (y2Values.some((v) => v !== null)) {
      series.push({
        name: y2Key,
        type: "line" as const,
        smooth: opts.curveType === "monotone",
        data: y2Values,
        itemStyle: { color: colors[1 % colors.length] },
        yAxisIndex: 1,
        animation: animate,
      });
    }
  } else {
    // Fallback: bars from yKey and a line overlay from yKey
    series.push({
      name: yKey,
      type: "bar" as const,
      data: chartData.map((r) => toNumber(r[yKey]) ?? 0),
      itemStyle: { color: colors[0] },
      yAxisIndex: 0,
      barMaxWidth: 40,
      animation: animate,
    });
    series.push({
      name: `${yKey} (line)`,
      type: "line" as const,
      smooth: opts.curveType === "monotone",
      data: chartData.map((r) => toNumber(r[yKey]) ?? 0),
      itemStyle: { color: colors[1 % colors.length] },
      yAxisIndex: 0,
      animation: animate,
    });
  }

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "axis", formatter: (params: any) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale) },
    legend: showLegend ? getLegendConfig(opts, isDark) : undefined,
    xAxis: { type: "category" as const, data: categoryData, show: !tiny, axisLabel: { rotate: opts.xAxisLabelRotate ?? (categoryData.length > 8 ? -30 : 0), fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: [
      { type: "value" as const, show: !tiny, name: axisScaleLabel(opts), nameLocation: "middle" as const, nameGap: 44, axisLabel: { formatter: (v: number) => formatAxisNumber(v, opts), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
      ...(dualAxis && !tiny ? [{ type: "value" as const, show: true, position: "right" as const, name: axisScaleLabel(opts), nameLocation: "middle" as const, nameGap: 44, axisLabel: { formatter: (v: number) => formatAxisNumber(v, opts), fontSize: 10, color: colorsForChart.text }, splitLine: { show: false } }] : []),
    ],
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  const markLineData = buildReferenceLines(opts.referenceLines);
  if (markLineData) option.series[0].markLine = { symbol: "none", data: markLineData };

  return option;
}
