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


export function buildRadarOption(
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
  const { data: radarData, series: radarSeries } = prepareRadarData(data, { subjectKey: xKey, valueKey: yKey, seriesKey: groupKey });
  const indicator = radarData.map((r) => ({ name: String(r[xKey] ?? ""), max: opts.domainMax && opts.domainMax > 0 ? opts.domainMax : "auto" }));
  const colorsForChart = axisColors(isDark);

  const series = [{
    type: "radar" as const,
    data: radarSeries.map((name, i) => ({
      name,
      value: radarData.map((r) => toNumber(r[name]) ?? 0),
      itemStyle: { color: colors[i % colors.length] },
      areaStyle: { opacity: opts.fillOpacity ?? 0.25 },
      label: { show: !!opts.showLabels, fontSize: 9, color: colorsForChart.text },
    })),
  }];

  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item" },
    legend: !tiny && opts.showLegend !== false && radarSeries.length > 1 ? getLegendConfig(opts, isDark) : undefined,
    radar: { indicator, axisName: { color: colorsForChart.text, fontSize: 10 }, splitArea: { areaStyle: { color: ["transparent"] } }, splitLine: { lineStyle: { color: colorsForChart.grid } } },
    series,
    animation: !!opts.animate,
  };
}