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


export function buildGaugeOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const sub = widget.chartSubtype ?? "";
  const colorsForChart = axisColors(isDark);
  const animate = !!opts.animate;
  const values = data.map((r) => toNumber(r[yKey])).filter((v): v is number => v !== null);
  const value = values.length ? values[values.length - 1] : 0;
  const min = (opts.domainMin as number) ?? 0;
  const max = (opts.domainMax as number) ?? Math.max(100, Math.ceil(value * 1.2));
  const startAngle = sub === "semi" ? 180 : 90;
  const endAngle = sub === "semi" ? 0 : -270;
  const innerRadius = (opts.innerRadius as number) ?? 55;
  const outerRadius = (opts.outerRadius as number) ?? 80;

  const option: any = {
    aria: { enabled: true, description: `${widget.title || "Gauge"} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { formatter: `{b}: {c}` },
    series: [{
      type: "gauge" as const,
      startAngle,
      endAngle,
      min,
      max,
      radius: `${outerRadius}%`,
      progress: { show: true, width: outerRadius - innerRadius },
      axisLine: { lineStyle: { width: outerRadius - innerRadius, color: [[1, colorsForChart.grid]] } },
      axisTick: { show: !tiny, splitNumber: 5 },
      splitLine: { show: !tiny, length: 8, lineStyle: { width: 2, color: colorsForChart.line } },
      axisLabel: { show: !tiny, distance: 12, color: colorsForChart.text, fontSize: 10, formatter: (v: number) => formatNumber(v, opts.yAxisFormat) },
      anchor: { show: true, showAbove: true, size: 12, itemStyle: { borderColor: colors[0] } },
      title: { show: !tiny, offsetCenter: [0, "30%"], fontSize: 12, color: colorsForChart.text },
      detail: {
        valueAnimation: animate,
        fontSize: tiny ? 14 : 24,
        color: colorsForChart.text,
        formatter: (v: number) => formatNumber(v, opts.yAxisFormat),
        offsetCenter: [0, "-15%"],
      },
      data: [{ value, name: widget.title || yKey }],
    }],
  };
  return option;
}