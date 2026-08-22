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


export function buildScatterOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const zKey = opts.zColumn || widget.y2Column || "";
  const isBubble = (opts.bubble || widget.chartSubtype === "bubble") && !!zKey;
  const showGrid = !tiny && opts.showGrid !== false;
  const colorsForChart = axisColors(isDark);
  const animate = !!opts.animate;

  const seriesData = data.map((r) => {
    const x = toNumber(r[xKey]);
    const y = toNumber(r[yKey]);
    const z = isBubble ? toNumber(r[zKey]) ?? undefined : undefined;
    if (x === null || y === null) return null;
    return z !== undefined ? [x, y, z] as number[] : [x, y] as number[];
  }).filter((d): d is number[] => d !== null);

  const isEffectScatter = widget.type === "effect_scatter";
  const series: any[] = [{
    name: yKey,
    type: isEffectScatter ? ("effectScatter" as const) : ("scatter" as const),
    data: seriesData,
    symbolSize: isBubble ? (p: any) => Math.max(6, Math.min(40, (p.data?.[2] ?? 5) / 2)) : isEffectScatter ? 18 : 10,
    itemStyle: { color: colors[0] },
    label: { show: !!opts.showLabels, fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value?.[1] ?? 0), opts.yAxisFormat, undefined, opts.currencySymbol) },
    animation: animate,
    ...(isEffectScatter ? { rippleEffect: { brushType: "stroke" } } : {}),
  }];

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", formatter: (p: any) => tooltipScatterFormatter(p, xKey, yKey, zKey, opts.yAxisFormat, opts.currencySymbol) },
    legend: !tiny && opts.showLegend !== false ? getLegendConfig(opts, isDark) : undefined,
    xAxis: { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat, undefined, opts.currencySymbol), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
    yAxis: { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat, undefined, opts.currencySymbol), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  if (opts.showTrendLine || widget.chartSubtype === "best_fit") {
    const reg = linearRegression(data, { xKey, yKey });
    if (reg) {
      option.series.push({
        name: "Trend",
        type: "line",
        symbol: "none",
        data: [[reg.p1.x, reg.p1.y], [reg.p2.x, reg.p2.y]],
        lineStyle: { color: colors[1 % colors.length], type: "dashed", width: 2 },
        animation: animate,
        silent: true,
      });
    }
  }

  addAnalyticalLayers(option, "scatter", data, xKey, yKey, opts, colors);

  return option;
}