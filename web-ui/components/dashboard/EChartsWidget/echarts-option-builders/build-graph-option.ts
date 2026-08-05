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


export function buildGraphOption(
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
  const nodeSet = new Set<string>();
  const links: { source: string; target: string; value: number }[] = [];
  for (const r of data) {
    const x = String(r[xKey] ?? "");
    const g = groupKey ? String(r[groupKey] ?? "") : "";
    const v = toNumber(r[yKey]) ?? 0;
    if (!x || !g || x === g) continue;
    nodeSet.add(x);
    nodeSet.add(g);
    links.push({ source: x, target: g, value: v });
  }
  if (nodeSet.size === 0 || links.length === 0) {
    return { title: { text: "Graph needs a second dimension (Group by) for links.", left: "center", top: "center", textStyle: { color: colorsForChart.text, fontSize: 12 } } };
  }
  const nodes = Array.from(nodeSet).map((name, i) => ({ name, symbolSize: 10 + (i % 3) * 4, itemStyle: { color: colors[i % colors.length] } }));
  return {
    backgroundColor: "transparent",
    tooltip: opts.showTooltip === false ? { show: false } : { trigger: "item" as const },
    series: [{
      type: "graph" as const,
      layout: "force" as const,
      data: nodes,
      links,
      roam: true,
      label: { show: !!opts.showLabels, position: "right" as const, fontSize: 9, color: colorsForChart.text },
      force: { repulsion: 80, edgeLength: [30, 80] },
      lineStyle: { color: colorsForChart.line, curveness: 0.2 },
      emphasis: { focus: "adjacency" as const, lineStyle: { width: 4 } },
    }],
  };
}