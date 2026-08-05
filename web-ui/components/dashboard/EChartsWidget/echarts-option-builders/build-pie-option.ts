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


export function buildPieOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const sub = widget.chartSubtype ?? "";
  const donut = opts.innerRadius !== undefined ? opts.innerRadius > 0 : sub === "donut" || sub === "two_level" || sub === "gauge";
  const inner = opts.innerRadius ?? (sub === "donut" ? 55 : sub === "two_level" ? 45 : sub === "gauge" ? 55 : 0);
  const outer = opts.outerRadius ?? 80;
  const start = opts.startAngle ?? (sub === "gauge" ? 180 : 90);
  const end = opts.endAngle ?? (sub === "gauge" ? 0 : -270);
  const pad = opts.paddingAngle ?? 0;
  const maxSlices = opts.maxSlices ?? 7;
  const groupSmall = opts.groupSmallSlices !== false;

  const labelMode = opts.labelMode ?? (sub === "gauge" ? "value" : "percentage");
  const labelFormatter = (p: any) => {
    if (labelMode === "none") return "";
    if (labelMode === "name") return p.name;
    if (labelMode === "value") return formatNumber(Number(p.value ?? 0), opts.yAxisFormat);
    return `${p.name}\n${p.percent}%`;
  };

  const pieData = preparePieData(data, { nameKey: xKey, valueKey: yKey, maxSlices, groupSmallSlices: groupSmall }).map((d, i) => ({
    name: String(d[xKey] ?? ""),
    value: toNumber(d[yKey]) ?? 0,
    itemStyle: { color: colors[i % colors.length] },
  }));

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false ? { show: false } : { trigger: "item", formatter: (p: any) => `${p.name}: ${formatNumber(Number(p.value ?? 0), opts.yAxisFormat)} (${p.percent}%)` },
    legend: opts.showLegend !== false ? getLegendConfig(opts, isDark) : undefined,
    series: [{
      type: "pie" as const,
      radius: donut ? [`${inner}%`, `${outer}%`] : `${outer}%`,
      startAngle: start,
      endAngle: end,
      padAngle: pad,
      data: pieData,
      label: { show: labelMode !== "none", formatter: labelFormatter, fontSize: 10, color: isDark ? "#cbd5e1" : "#475569" },
      itemStyle: { borderRadius: 4, borderColor: isDark ? "#0f172a" : "#fff", borderWidth: 1 },
      emphasis: { itemStyle: { shadowBlur: 4, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.2)" } },
    }],
  };

  if (sub === "two_level") {
    const groupKey = opts.innerGroupColumn || widget.groupByColumn || "";
    if (groupKey) {
      const grouped = prepareTreemapData(data, { nameKey: xKey, valueKey: yKey, groupKey });
      option.series[0].data = grouped.map((g, i) => ({
        name: g.name,
        value: (g.children ?? []).reduce((s, c) => s + (c.size ?? 0), 0),
        itemStyle: { color: colors[i % colors.length] },
        children: (g.children ?? []).map((c, j) => ({ name: c.name, value: c.size ?? 0, itemStyle: { color: colors[(i + j + 1) % colors.length] } })),
      }));
    }
  }

  if (sub === "gauge") {
    option.series = pieData.slice(0, 1).map((d) => ({
      type: "gauge" as const,
      startAngle: start,
      endAngle: end,
      min: opts.domainMin ?? 0,
      max: opts.domainMax && opts.domainMax > 0 ? opts.domainMax : Math.max(100, d.value * 1.2),
      detail: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 14, color: isDark ? "#cbd5e1" : "#475569" },
      data: [{ value: d.value, name: d.name }],
      axisLine: { lineStyle: { color: [[1, colors[0]]], width: 20 } },
      splitLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
      pointer: { show: true, width: 4, itemStyle: { color: colors[1 % colors.length] } },
    }));
    option.legend = undefined;
  }

  return option;
}