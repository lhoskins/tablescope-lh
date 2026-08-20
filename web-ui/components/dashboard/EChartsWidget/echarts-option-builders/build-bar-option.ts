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



export function buildBarOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  chartData: Row[],
  seriesNames: string[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const sub = widget.chartSubtype ?? "";
  const horizontal = opts.barLayout === "horizontal" || sub === "horizontal_bar" || sub === "stacked_horizontal" || sub === "population_pyramid";
  const stackMode = opts.stackMode ?? (sub === "stacked_bar" || sub === "stacked_horizontal" ? "stacked" : sub === "positive_negative" || sub === "waterfall" ? "none" : "none");
  const stacked = stackMode !== "none";
  const percent = stackMode === "percent";
  const showGrid = !tiny && opts.showGrid !== false;
  const showLegend = !tiny && opts.showLegend !== false;
  const animate = !!opts.animate;
  const colorsForChart = axisColors(isDark);

  let workingData = chartData;
  let workingNames = seriesNames;

  if (percent && seriesNames.length > 0) {
    workingData = toPercentStacked(chartData, xKey, seriesNames);
  }

  const categoryData = workingData.map((r) => String(r[xKey] ?? ""));

  const series: any[] = [];

  if (sub === "waterfall") {
    const wf = prepareWaterfallData(workingData, { nameKey: xKey, valueKey: yKey });
    series.push(
      { name: "Base", type: "bar", stack: "wf", data: wf.map((d) => d.base), itemStyle: { color: "transparent" }, silent: true },
      { name: "Change", type: "bar", stack: "wf", data: wf.map((d) => d.delta), itemStyle: { color: (p: any) => (p.value >= 0 ? "#16a34a" : "#dc2626") }, label: { show: !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(wf[p.dataIndex]?.value ?? 0), opts.yAxisFormat, opts.valueScale) } }
    );
  } else if (sub === "population_pyramid") {
    const names = workingNames.length >= 2 ? [workingNames[0], workingNames[1]] : [yKey, workingNames[0] ?? yKey];
    if (names[1] === yKey) names[1] = names[0];
    series.push(
      { name: names[0], type: "bar", stack: "pyramid", data: workingData.map((r) => -(toNumber(r[names[0]]) ?? 0)), itemStyle: { color: colors[0] } },
      { name: names[1], type: "bar", stack: "pyramid", data: workingData.map((r) => toNumber(r[names[1]]) ?? 0), itemStyle: { color: colors[1 % colors.length] } }
    );
  } else {
    const names = workingNames.length > 0 ? workingNames : [yKey];
    const stack = stacked ? "total" : undefined;
    series.push(
      ...names.map((name, i) => ({
        name,
        type: "bar" as const,
        stack,
        data: workingData.map((r) => {
          const v = toNumber(r[name]);
          return v === null ? 0 : v;
        }),
        itemStyle: {
          color: (p: any) => {
            if (opts.colorBySign || sub === "positive_negative") {
              const v = Array.isArray(p.data) ? p.data[1] : p.value;
              return v >= 0 ? "#16a34a" : "#dc2626";
            }
            return colors[i % colors.length];
          },
          borderRadius: opts.roundedCorners === false ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
        },
        label: { show: !tiny && !!opts.showLabels, position: horizontal ? "right" : "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat, opts.valueScale) },
        showBackground: !!opts.showBackground,
        backgroundStyle: { color: colorsForChart.grid },
        barMaxWidth: 48,
        animation: animate,
      }))
    );
  }

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (params: any) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale) },
    legend: showLegend ? getLegendConfig(opts, isDark) : undefined,
    xAxis: horizontal
      ? { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(Math.abs(v), opts.yAxisFormat, opts.valueScale), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined }
      : { type: "category" as const, data: categoryData, show: !tiny, axisLabel: { rotate: opts.xAxisLabelRotate ?? (categoryData.length > 8 ? -30 : 0), fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: horizontal
      ? { type: "category" as const, data: categoryData, show: !tiny, axisLabel: { fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } }
      : { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat, opts.valueScale), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  if (sub !== "waterfall" && sub !== "population_pyramid") {
    const markLineData = buildReferenceLines(opts.referenceLines);
    if (markLineData) option.series[0].markLine = { symbol: "none", data: markLineData };
    addAnalyticalLayers(option, "bar", chartData, xKey, yKey, opts, colors);
  }

  return option;
}