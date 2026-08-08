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


export function buildTreeOption(
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
  const total = data.reduce((sum, r) => sum + (toNumber(r[yKey]) ?? 0), 0);
  const root = {
    name: widget.title || yKey,
    value: total,
    children: Array.from(byX.values()).map((n) => ({
      name: n.name,
      value: n.value,
      children: n.children.size ? Array.from(n.children.values()) : undefined,
    })),
  };
  return {
    backgroundColor: "transparent",
    tooltip: opts.showTooltip === false ? { show: false } : { trigger: "item" as const },
    series: [{
      type: "tree" as const,
      data: [root],
      top: "10%",
      left: "10%",
      bottom: "10%",
      right: "20%",
      symbolSize: 7,
      label: { position: "left" as const, verticalAlign: "middle" as const, align: "right" as const, fontSize: 10, color: colorsForChart.text },
      leaves: { label: { position: "right" as const, verticalAlign: "middle" as const, align: "left" as const } },
      color: colors,
      lineStyle: { color: colorsForChart.line },
    }],
  };
}