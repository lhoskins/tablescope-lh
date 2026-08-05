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



export function addAnalyticalLayers(
  option: any,
  type: "line" | "bar" | "area" | "scatter",
  data: Row[],
  xKey: string,
  yKey: string,
  opts: VisualizationOptions,
  colors: string[]
) {
  if (type === "line" || type === "area" || type === "scatter") {
    if (opts.showRegressionLine) {
      const reg = linearRegression(data, { xKey, yKey });
      if (reg) {
        const firstX = String(data[0]?.[xKey] ?? "");
        const lastX = String(data[data.length - 1]?.[xKey] ?? "");
        option.series.push({
          name: "Regression",
          type: "line",
          symbol: "none",
          smooth: false,
          lineStyle: { color: colors[colors.length - 1] ?? "#ef4444", width: 2, type: "dashed" },
          data: type === "scatter" ? [[reg.p1.x, reg.p1.y], [reg.p2.x, reg.p2.y]] : [[firstX, reg.p1.y], [lastX, reg.p2.y]],
          tooltip: { show: false },
          silent: true,
        });
      }
    }
  }

  const values = data.map((r) => toNumber(r[yKey])).filter((v): v is number => v !== null);
  if (values.length === 0) return;

  const explicitPoints = (opts.markedIndices ?? []).filter(
    (i) => Number.isInteger(i) && i >= 0 && i < data.length,
  );
  const explicitChangePoint =
    typeof opts.markedChangePointIndex === "number" &&
    opts.markedChangePointIndex >= 0 &&
    opts.markedChangePointIndex < data.length
      ? opts.markedChangePointIndex
      : null;

  if (
    opts.showControlLimits ||
    opts.showAnomalies ||
    opts.showChangePoint ||
    explicitPoints.length > 0 ||
    explicitChangePoint !== null
  ) {
    if (!option.series[0].markLine) option.series[0].markLine = { symbol: "none", data: [] };
    if (!option.series[0].markPoint) option.series[0].markPoint = { data: [] };
  }

  if (opts.showControlLimits) {
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const std = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length);
    const upper = mean + 2 * std;
    const lower = mean - 2 * std;
    option.series[0].markLine.data.push(
      { yAxis: upper, label: { formatter: "+2σ", position: "insideEndTop" }, lineStyle: { color: "#f59e0b", type: "dashed" } },
      { yAxis: lower, label: { formatter: "-2σ", position: "insideEndTop" }, lineStyle: { color: "#f59e0b", type: "dashed" } }
    );
  }

  // Points an analysis actually flagged. These take precedence over the 2-sigma
  // re-derivation below: a method that fits a model (ETS, STL) can flag a point
  // that sits inside 2 sigma of the mean, and marking a different point than the
  // one the finding names would contradict the text beside the chart.
  if (explicitPoints.length > 0) {
    explicitPoints.forEach((i) => {
      const v = toNumber(data[i]?.[yKey]);
      if (v === null) return;
      option.series[0].markPoint.data.push({
        coord: [i, v],
        value: formatNumber(v, opts.yAxisFormat),
        itemStyle: { color: "#ef4444" },
      });
    });
  } else if (opts.showAnomalies) {
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const std = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length);
    const threshold = 2 * std;
    data.forEach((r, i) => {
      const v = toNumber(r[yKey]);
      if (v !== null && Math.abs(v - mean) > threshold) {
        option.series[0].markPoint.data.push({
          coord: [i, v],
          value: formatNumber(v, opts.yAxisFormat),
          itemStyle: { color: "#ef4444" },
        });
      }
    });
  }

  if (explicitChangePoint !== null) {
    const v = toNumber(data[explicitChangePoint]?.[yKey]);
    if (v !== null) {
      option.series[0].markPoint.data.push({
        coord: [explicitChangePoint, v],
        value: "Change",
        itemStyle: { color: "#8b5cf6" },
      });
    }
  } else if (opts.showChangePoint) {
    let maxDiff = 0;
    let maxIdx = 0;
    for (let i = 1; i < values.length; i++) {
      const diff = Math.abs(values[i] - values[i - 1]);
      if (diff > maxDiff) {
        maxDiff = diff;
        maxIdx = i;
      }
    }
    option.series[0].markPoint.data.push({
      coord: [maxIdx, values[maxIdx]],
      value: "Change",
      itemStyle: { color: "#8b5cf6" },
    });
  }
}