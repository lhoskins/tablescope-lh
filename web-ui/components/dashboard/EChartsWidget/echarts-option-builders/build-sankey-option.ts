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


export function buildSankeyOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const targetKey = opts.targetColumn || widget.groupByColumn || "";
  const graph = targetKey ? prepareSankeyData(data, { sourceKey: xKey, targetKey, valueKey: yKey }) : { nodes: [], links: [] };

  if (graph.nodes.length === 0 || graph.links.length === 0) {
    return { _noData: true, title: { text: "Sankey needs a source (X), a target (Group by), and a numeric value (Y).", left: "center", top: "center", textStyle: { color: isDark ? "#94a3b8" : "#94a3b8", fontSize: 12 } } };
  }

  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", triggerOn: "mousemove" },
    series: [{
      type: "sankey" as const,
      data: graph.nodes,
      links: graph.links,
      nodePadding: opts.nodePadding ?? 20,
      nodeWidth: opts.nodeWidth ?? 12,
      lineStyle: { color: "gradient", curveness: 0.5, opacity: 0.4 },
      itemStyle: { color: colors[0], borderColor: isDark ? "#0f172a" : "#fff" },
      label: { color: isDark ? "#cbd5e1" : "#475569", fontSize: 10 },
      animation: !!opts.animate,
    }],
    animation: !!opts.animate,
  };
}