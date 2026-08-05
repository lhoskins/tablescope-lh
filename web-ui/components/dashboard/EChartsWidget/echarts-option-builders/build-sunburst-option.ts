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


export function buildSunburstOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const groupKey = widget.groupByColumn || "";
  const colorsForChart = axisColors(isDark);
  const byX = new Map<string, { name: string; value: number; children: Map<string, { name: string; value: number }> }>();
  for (const r of data) {
    const x = String(r[xKey] ?? "");
    const g = groupKey ? String(r[groupKey] ?? "") : "";
    const v = toNumber(r[yKey]) ?? 0;
    if (!byX.has(x)) byX.set(x, { name: x, value: 0, children: new Map() });
    const node = byX.get(x)!;
    node.value += v;
    if (groupKey && g && g !== x) {
      if (!node.children.has(g)) node.children.set(g, { name: g, value: 0 });
      node.children.set(g, { ...node.children.get(g)!, value: (node.children.get(g)!.value || 0) + v });
    }
  }
  const sunData = Array.from(byX.values()).map((n) => ({
    name: n.name,
    value: n.value,
    children: n.children.size ? Array.from(n.children.values()) : undefined,
  }));
  return {
    backgroundColor: "transparent",
    tooltip: opts.showTooltip === false ? { show: false } : { trigger: "item" as const },
    series: [{
      type: "sunburst" as const,
      data: sunData,
      radius: [0, "90%"],
      label: { rotate: "radial" as const, color: colorsForChart.text, fontSize: 10 },
      itemStyle: { borderColor: isDark ? "#0f172a" : "#fff", borderWidth: 1 },
      color: colors,
    }],
  };
}