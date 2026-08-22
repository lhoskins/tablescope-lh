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



export function buildLineOption(
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
  const smooth = opts.curveType === "monotone" || (!opts.curveType && sub === "smooth_line");
  const step = opts.curveType === "step" ? "middle" : undefined;
  const dash = opts.lineStyle === "dashed" || sub === "dashed_line" ? "dashed" : "solid";
  const animate = opts.animate || sub === "animated_line";
  const dualAxis = opts.dualAxis || sub === "biaxial_line" || sub === "dual_line";
  const colorsForChart = axisColors(isDark);

  const names = seriesNames.length > 0 ? seriesNames : [yKey];
  const rightSet = new Set(opts.rightAxisSeries ?? (dualAxis && names.length > 1 ? [names[1]] : []));

  const signedPercentAxis = opts.yAxisFormat === "percent" && opts.signedPercentAxis;
  const yAxisFormatter = signedPercentAxis
    ? signedPercent
    : (v: number) => formatAxisNumber(v, opts);
  const tooltipFormatterFn = opts.percentChangeTooltip
    ? (params: any) => percentChangeTooltipFormatter(params)
    : (params: any) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale, opts.currencySymbol);

  const series = names.map((name, i) => ({
    name,
    type: "line" as const,
    smooth,
    step,
    yAxisIndex: dualAxis && rightSet.has(name) ? 1 : 0,
    connectNulls: !!opts.connectNulls,
    showSymbol: !!opts.showDots,
    data: chartData.map((row) => {
      const v = toNumber(row[name]);
      if (v === null) return null;
      return opts.percentChangeTooltip ? { value: v, ...row } : v;
    }),
    itemStyle: opts.colorBySign ? undefined : { color: colors[i % colors.length] },
    lineStyle: { width: 2.5, type: dash as any },
    label: { show: !tiny && !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat, opts.valueScale, opts.currencySymbol) },
    areaStyle: widget.type === "area" ? { opacity: opts.fillOpacity ?? 0.35 } : undefined,
    stack: widget.type === "area" && opts.stackMode && opts.stackMode !== "none" ? "total" : undefined,
    animation: animate,
  }));

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "axis", formatter: tooltipFormatterFn },
    legend: showLegend ? getLegendConfig(opts, isDark) : undefined,
    xAxis: { type: "category" as const, data: chartData.map((r) => String(r[xKey] ?? "")), show: !tiny, axisLabel: { rotate: opts.xAxisLabelRotate ?? (chartData.length > 8 ? -30 : 0), fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: [
      { type: "value" as const, show: !tiny, name: axisScaleLabel(opts), nameLocation: "middle" as const, nameGap: 44, axisLabel: { formatter: yAxisFormatter, fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
      ...(dualAxis && !tiny ? [{ type: "value" as const, show: true, position: "right" as const, name: axisScaleLabel(opts), nameLocation: "middle" as const, nameGap: 44, axisLabel: { formatter: yAxisFormatter, fontSize: 10, color: colorsForChart.text }, splitLine: { show: false } }] : []),
    ],
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  if (opts.colorBySign) {
    option.visualMap = {
      show: false,
      type: "piecewise" as const,
      pieces: [
        { gt: 0, color: "#16a34a" },
        { lt: 0, color: "#dc2626" },
        { value: 0, color: "#6b7280" },
      ],
      outOfRange: { color: "#6b7280" },
    };
  }

  const markLineData = buildReferenceLines(opts.referenceLines);
  if (markLineData) {
    option.series[0].markLine = { symbol: "none", data: markLineData };
  }

  addAnalyticalLayers(option, widget.type as any, chartData, xKey, yKey, opts, colors);

  if (y2Key && !seriesNames.length && widget.type === "line" && (sub === "biaxial_line" || sub === "dual_line")) {
    const y2Values = chartData.map((r) => toNumber(r[y2Key]));
    if (y2Values.some((v) => v !== null)) {
      option.series.push({
        name: y2Key,
        type: "line" as const,
        smooth,
        yAxisIndex: 1,
        data: y2Values,
        itemStyle: { color: colors[1 % colors.length] },
        lineStyle: { width: 2, type: dash as any },
        animation: animate,
      });
    }
  }

  return option;
}
