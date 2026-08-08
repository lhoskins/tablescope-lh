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


export function buildFunnelOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const funnelData = prepareFunnelData(data, { nameKey: xKey, valueKey: yKey }).map((d, i) => ({ ...d, itemStyle: { color: colors[i % colors.length] } }));

  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", formatter: (p: any) => `${p.name}: ${formatNumber(Number(p.value ?? 0), opts.yAxisFormat)}` },
    legend: !tiny && opts.showLegend ? getLegendConfig(opts, isDark) : undefined,
    series: [{
      type: "funnel" as const,
      data: funnelData,
      label: { show: opts.showLabels !== false, fontSize: 10, color: isDark ? "#cbd5e1" : "#475569" },
      itemStyle: { borderColor: isDark ? "#0f172a" : "#fff", borderWidth: 1 },
      animation: !!opts.animate,
    }],
    animation: !!opts.animate,
  };
}