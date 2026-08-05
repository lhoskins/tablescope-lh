"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import type { ChartClickEvent, ReferenceLineConfig, VisualizationOptions, WidgetConfig } from "../types";
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
import { CanvasRenderer } from "echarts/renderers";import { formatNumber } from "./format-number";
import { signedPercent } from "./signed-percent";



export function percentChangeTooltipFormatter(params: any) {
  const rows = Array.isArray(params) ? params : [params];
  if (!rows.length) return "";
  const axis = rows[0].axisValueLabel ?? rows[0].name ?? "";
  return (
    axis +
    rows
      .map((p: any) => {
        const v = typeof p.value === "number" ? p.value : Number(p.value ?? 0);
        const data = p.data;
        const current =
          typeof data?.currentValue === "number"
            ? formatNumber(data.currentValue)
            : "—";
        const previous =
          typeof data?.previousValue === "number"
            ? formatNumber(data.previousValue)
            : "—";
        const change = typeof v === "number" ? signedPercent(v) : "—";
        return `<br/>${p.marker} ${p.seriesName}<br/>Period: ${axis}<br/>% change: ${change}<br/>Current: ${current}<br/>Previous: ${previous}`;
      })
      .join("")
  );
}