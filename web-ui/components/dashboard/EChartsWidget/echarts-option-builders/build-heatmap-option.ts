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


export function buildHeatmapOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const groupKey = widget.groupByColumn;
  if (!groupKey || data.length === 0) {
    return {
      _noData: true,
      title: {
        text: "Heatmap needs an X dimension, a Y dimension, and a numeric value.",
        left: "center",
        top: "center",
        textStyle: { color: isDark ? "#94a3b8" : "#94a3b8", fontSize: 12 },
      },
    };
  }
  const xValues = [...new Set(data.map((r) => String(r[xKey] ?? "")))].sort();
  const yValues = [...new Set(data.map((r) => String(r[groupKey] ?? "")))].sort();
  const valueData: [number, number, number][] = [];
  const values: number[] = [];
  for (const r of data) {
    const x = String(r[xKey] ?? "");
    const y = String(r[groupKey] ?? "");
    const v = toNumber(r[yKey]) ?? 0;
    const xi = xValues.indexOf(x);
    const yi = yValues.indexOf(y);
    if (xi >= 0 && yi >= 0) {
      valueData.push([xi, yi, v]);
      values.push(v);
    }
  }
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const colorsForChart = axisColors(isDark);
  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip:
      opts.showTooltip === false || tiny
        ? { show: false }
        : {
            position: "top",
            formatter: (p: any) =>
              `${xValues[p.data[0]] ?? ""} / ${yValues[p.data[1]] ?? ""}: ${formatNumber(Number(p.data[2] ?? 0), opts.yAxisFormat, undefined, opts.currencySymbol)}`,
          },
    grid: { top: 10, bottom: 50, left: 80, right: 20, containLabel: true },
    xAxis: {
      type: "category" as const,
      data: xValues,
      splitArea: { show: true },
      axisLabel: { fontSize: 10, color: colorsForChart.text },
    },
    yAxis: {
      type: "category" as const,
      data: yValues,
      splitArea: { show: true },
      axisLabel: { fontSize: 10, color: colorsForChart.text },
    },
    visualMap: {
      min,
      max: max || 1,
      calculable: true,
      orient: "horizontal" as const,
      left: "center" as const,
      bottom: 0,
      inRange: { color: [colors[0], colors[1 % colors.length], colors[2 % colors.length]] },
    },
    series: [
      {
        name: yKey,
        type: "heatmap" as const,
        data: valueData,
        label: { show: !tiny && !!opts.showLabels, fontSize: 9 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.5)" } },
      },
    ],
    animation: !!opts.animate,
  };
}