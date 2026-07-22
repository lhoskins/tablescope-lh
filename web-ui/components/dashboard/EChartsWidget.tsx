"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChartClickEvent, ReferenceLineConfig, VisualizationOptions, WidgetConfig } from "./types";
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
  RadarChart,
  TreemapChart,
  FunnelChart,
  SankeyChart,
  GaugeChart,
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
} from "echarts/components";
import { LegacyGridContainLabel } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";

// Tree-shaken ECharts modules — only these are bundled.
echarts.use([
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  RadarChart,
  TreemapChart,
  FunnelChart,
  SankeyChart,
  GaugeChart,
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
  LegacyGridContainLabel,
  CanvasRenderer,
]);

type EChartsInit = typeof echarts.init;
type EChartsType = ReturnType<EChartsInit>;

type Props = {
  widget: WidgetConfig;
  data: Row[];
  xKey: string;
  yKey: string;
  y2Key: string;
  chartData: Row[];
  seriesNames: string[];
  onElementClick?: (event: ChartClickEvent) => void;
};

const BASE_COLORS = [
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#06b6d4",
  "#6366f1",
  "#84cc16",
  "#f97316",
];

function getPalette(scheme: string | undefined, isDark: boolean): string[] {
  switch (scheme) {
    case "ocean":
      return ["#0ea5e9", "#06b6d4", "#14b8a6", "#3b82f6", "#6366f1", "#a855f7"];
    case "forest":
      return ["#22c55e", "#16a34a", "#15803d", "#84cc16", "#eab308", "#a16207"];
    case "warm":
      return ["#f97316", "#ef4444", "#f59e0b", "#db2777", "#8b5cf6", "#9333ea"];
    case "monochrome":
      return isDark
        ? ["#94a3b8", "#64748b", "#475569", "#334155", "#1e293b"]
        : ["#475569", "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0"];
    default:
      return BASE_COLORS;
  }
}

function formatNumber(v: number, format?: string): string {
  if (!Number.isFinite(v)) return "—";
  if (format === "percent") return `${(v * 100).toFixed(1)}%`;
  if (format === "currency") {
    if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
    return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  }
  if (format === "compact") {
    if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  }
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function useChartTheme() {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    if (typeof document === "undefined" || typeof window === "undefined") return;
    const update = () => {
      const dark =
        document.documentElement.classList.contains("dark") ||
        window.matchMedia("(prefers-color-scheme: dark)").matches;
      setIsDark(dark);
    };
    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (e: MediaQueryListEvent) => {
      setIsDark(document.documentElement.classList.contains("dark") || e.matches);
    };
    if ("addEventListener" in mq) {
      mq.addEventListener("change", listener);
    } else {
      // eslint-disable-next-line
      (mq as any).addListener(listener);
    }
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => {
      if ("removeEventListener" in mq) {
        mq.removeEventListener("change", listener);
      } else {
        // eslint-disable-next-line
        (mq as any).removeListener(listener);
      }
      observer.disconnect();
    };
  }, []);
  return isDark;
}

function getLegendConfig(opts: VisualizationOptions, isDark: boolean) {
  if (opts.showLegend === false || opts.legendPosition === "none" || opts.tinyMode) return undefined;
  const pos = opts.legendPosition ?? "bottom";
  const textColor = isDark ? "#cbd5e1" : "#475569";
  const cfg: any = { textStyle: { color: textColor, fontSize: 11 }, itemWidth: 12, itemHeight: 8 };
  if (pos === "top") cfg.top = 0;
  else if (pos === "bottom") cfg.bottom = 0;
  else if (pos === "left") cfg.left = 0;
  else if (pos === "right") cfg.right = 0;
  return cfg;
}

function commonGrid(tiny: boolean) {
  return tiny
    ? { top: 2, right: 2, bottom: 2, left: 2, containLabel: false }
    : { top: 28, right: 20, bottom: 32, left: 10, containLabel: true };
}

function axisColors(isDark: boolean) {
  return {
    text: isDark ? "#cbd5e1" : "#475569",
    line: isDark ? "#334155" : "#e2e8f0",
    grid: isDark ? "#1e293b" : "#f1f5f9",
  };
}

function buildReferenceLines(refs: ReferenceLineConfig[] | undefined) {
  if (!refs || refs.length === 0) return undefined;
  return refs.map((r) => ({
    [r.axis === "x" ? "xAxis" : "yAxis"]: r.value,
    label: r.label ? { formatter: r.label, position: "insideEndTop" as const } : undefined,
    lineStyle: { color: "#ef4444", type: "dashed" as const, width: 1.5 },
  }));
}

function addAnalyticalLayers(
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

  if (opts.showControlLimits || opts.showAnomalies || opts.showChangePoint) {
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

  if (opts.showAnomalies) {
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

  if (opts.showChangePoint) {
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

function buildLineOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  y2Key: string,
  chartData: Row[],
  seriesNames: string[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const sub = widget.chartSubtype ?? "";
  const showGrid = !tiny && opts.showGrid !== false;
  const showLegend = !tiny && opts.showLegend !== false;
  const smooth = opts.curveType === "monotone" || (!opts.curveType && sub === "smooth_line");
  const step = opts.curveType === "step" ? "middle" : undefined;
  const dash = opts.lineStyle === "dashed" || sub === "dashed_line" ? "dashed" : "solid";
  const animate = opts.animate || sub === "animated_line";
  const dualAxis = opts.dualAxis || sub === "biaxial_line" || sub === "dual_line";
  const colorsForChart = axisColors(isDark);

  const names = seriesNames.length > 0 ? seriesNames : [yKey];
  const rightSet = new Set(opts.rightAxisSeries ?? (dualAxis && names.length > 1 ? [names[1]] : []));

  const series = names.map((name, i) => ({
    name,
    type: "line" as const,
    smooth,
    step,
    yAxisIndex: dualAxis && rightSet.has(name) ? 1 : 0,
    connectNulls: !!opts.connectNulls,
    showSymbol: !!opts.showDots,
    data: chartData.map((row) => {
      const v = toNumber(row[name]);
      return v === null ? null : v;
    }),
    itemStyle: { color: colors[i % colors.length] },
    lineStyle: { width: 2.5, type: dash as any },
    label: { show: !tiny && !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat) },
    areaStyle: widget.type === "area" ? { opacity: opts.fillOpacity ?? 0.35 } : undefined,
    stack: widget.type === "area" && opts.stackMode && opts.stackMode !== "none" ? "total" : undefined,
    animation: animate,
  }));

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "axis", formatter: (params: any) => tooltipFormatter(params, opts.yAxisFormat) },
    legend: showLegend ? getLegendConfig(opts, isDark) : undefined,
    xAxis: { type: "category" as const, data: chartData.map((r) => String(r[xKey] ?? "")), show: !tiny, axisLabel: { rotate: opts.xAxisLabelRotate ?? (chartData.length > 8 ? -30 : 0), fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: [
      { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
      ...(dualAxis && !tiny ? [{ type: "value" as const, show: true, position: "right" as const, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: { show: false } }] : []),
    ],
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  const markLineData = buildReferenceLines(opts.referenceLines);
  if (markLineData) {
    option.series[0].markLine = { symbol: "none", data: markLineData };
  }

  addAnalyticalLayers(option, widget.type as any, chartData, xKey, yKey, opts, colors);

  if (y2Key && !seriesNames.length && widget.type === "line" && (sub === "biaxial_line" || sub === "dual_line")) {
    const y2Values = chartData.map((r) => toNumber(r[y2Key]));
    if (y2Values.some((v) => v !== null)) {
      option.series.push({
        name: y2Key,
        type: "line" as const,
        smooth,
        yAxisIndex: 1,
        data: y2Values,
        itemStyle: { color: colors[1 % colors.length] },
        lineStyle: { width: 2, type: dash as any },
        animation: animate,
      });
    }
  }

  return option;
}

function buildBarOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  chartData: Row[],
  seriesNames: string[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const sub = widget.chartSubtype ?? "";
  const horizontal = opts.barLayout === "horizontal" || sub === "horizontal_bar" || sub === "stacked_horizontal" || sub === "population_pyramid";
  const stackMode = opts.stackMode ?? (sub === "stacked_bar" || sub === "stacked_horizontal" ? "stacked" : sub === "positive_negative" || sub === "waterfall" ? "none" : "none");
  const stacked = stackMode !== "none";
  const percent = stackMode === "percent";
  const showGrid = !tiny && opts.showGrid !== false;
  const showLegend = !tiny && opts.showLegend !== false;
  const animate = !!opts.animate;
  const colorsForChart = axisColors(isDark);

  let workingData = chartData;
  let workingNames = seriesNames;

  if (percent && seriesNames.length > 0) {
    workingData = toPercentStacked(chartData, xKey, seriesNames);
  }

  const categoryData = workingData.map((r) => String(r[xKey] ?? ""));

  const series: any[] = [];

  if (sub === "waterfall") {
    const wf = prepareWaterfallData(workingData, { nameKey: xKey, valueKey: yKey });
    series.push(
      { name: "Base", type: "bar", stack: "wf", data: wf.map((d) => d.base), itemStyle: { color: "transparent" }, silent: true },
      { name: "Change", type: "bar", stack: "wf", data: wf.map((d) => d.delta), itemStyle: { color: (p: any) => (p.value >= 0 ? "#16a34a" : "#dc2626") }, label: { show: !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(wf[p.dataIndex]?.value ?? 0), opts.yAxisFormat) } }
    );
  } else if (sub === "population_pyramid") {
    const names = workingNames.length >= 2 ? [workingNames[0], workingNames[1]] : [yKey, workingNames[0] ?? yKey];
    if (names[1] === yKey) names[1] = names[0];
    series.push(
      { name: names[0], type: "bar", stack: "pyramid", data: workingData.map((r) => -(toNumber(r[names[0]]) ?? 0)), itemStyle: { color: colors[0] } },
      { name: names[1], type: "bar", stack: "pyramid", data: workingData.map((r) => toNumber(r[names[1]]) ?? 0), itemStyle: { color: colors[1 % colors.length] } }
    );
  } else {
    const names = workingNames.length > 0 ? workingNames : [yKey];
    const stack = stacked ? "total" : undefined;
    series.push(
      ...names.map((name, i) => ({
        name,
        type: "bar" as const,
        stack,
        data: workingData.map((r) => {
          const v = toNumber(r[name]);
          return v === null ? 0 : v;
        }),
        itemStyle: {
          color: (p: any) => {
            if (opts.colorBySign || sub === "positive_negative") {
              const v = Array.isArray(p.data) ? p.data[1] : p.value;
              return v >= 0 ? "#16a34a" : "#dc2626";
            }
            return colors[i % colors.length];
          },
          borderRadius: opts.roundedCorners === false ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
        },
        label: { show: !tiny && !!opts.showLabels, position: horizontal ? "right" : "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat) },
        showBackground: !!opts.showBackground,
        backgroundStyle: { color: colorsForChart.grid },
        barMaxWidth: 48,
        animation: animate,
      }))
    );
  }

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (params: any) => tooltipFormatter(params, opts.yAxisFormat) },
    legend: showLegend ? getLegendConfig(opts, isDark) : undefined,
    xAxis: horizontal
      ? { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(Math.abs(v), opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined }
      : { type: "category" as const, data: categoryData, show: !tiny, axisLabel: { rotate: opts.xAxisLabelRotate ?? (categoryData.length > 8 ? -30 : 0), fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: horizontal
      ? { type: "category" as const, data: categoryData, show: !tiny, axisLabel: { fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } }
      : { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  if (sub !== "waterfall" && sub !== "population_pyramid") {
    const markLineData = buildReferenceLines(opts.referenceLines);
    if (markLineData) option.series[0].markLine = { symbol: "none", data: markLineData };
    addAnalyticalLayers(option, "bar", chartData, xKey, yKey, opts, colors);
  }

  return option;
}

function buildPieOption(
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

function buildScatterOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const zKey = opts.zColumn || widget.y2Column || "";
  const isBubble = (opts.bubble || widget.chartSubtype === "bubble") && !!zKey;
  const showGrid = !tiny && opts.showGrid !== false;
  const colorsForChart = axisColors(isDark);
  const animate = !!opts.animate;

  const seriesData = data.map((r) => {
    const x = toNumber(r[xKey]);
    const y = toNumber(r[yKey]);
    const z = isBubble ? toNumber(r[zKey]) ?? undefined : undefined;
    if (x === null || y === null) return null;
    return z !== undefined ? [x, y, z] as number[] : [x, y] as number[];
  }).filter((d): d is number[] => d !== null);

  const series: any[] = [{
    name: yKey,
    type: "scatter" as const,
    data: seriesData,
    symbolSize: isBubble ? (p: any) => Math.max(6, Math.min(40, (p.data?.[2] ?? 5) / 2)) : 10,
    itemStyle: { color: colors[0] },
    label: { show: !!opts.showLabels, fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value?.[1] ?? 0), opts.yAxisFormat) },
    animation: animate,
  }];

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", formatter: (p: any) => tooltipScatterFormatter(p, xKey, yKey, zKey, opts.yAxisFormat) },
    legend: !tiny && opts.showLegend !== false ? getLegendConfig(opts, isDark) : undefined,
    xAxis: { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
    yAxis: { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  if (opts.showTrendLine || widget.chartSubtype === "best_fit") {
    const reg = linearRegression(data, { xKey, yKey });
    if (reg) {
      option.series.push({
        name: "Trend",
        type: "line",
        symbol: "none",
        data: [[reg.p1.x, reg.p1.y], [reg.p2.x, reg.p2.y]],
        lineStyle: { color: colors[1 % colors.length], type: "dashed", width: 2 },
        animation: animate,
        silent: true,
      });
    }
  }

  addAnalyticalLayers(option, "scatter", data, xKey, yKey, opts, colors);

  return option;
}

function buildRadarOption(
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

function buildRadialBarOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const inner = opts.innerRadius ?? 30;
  const outer = opts.outerRadius ?? 90;
  const start = opts.startAngle ?? 90;
  const end = opts.endAngle ?? -270;
  const max = opts.domainMax && opts.domainMax > 0 ? opts.domainMax : 100;
  const animate = !!opts.animate;
  const colorsForChart = axisColors(isDark);

  // Render each category as a gauge arc; multi-ring variant changes the radius.
  const rows = data.slice(0, 8).map((r, i) => ({
    name: String(r[xKey] ?? ""),
    value: toNumber(r[yKey]) ?? 0,
    color: colors[i % colors.length],
  }));

  const series = rows.map((r, i) => ({
    type: "gauge" as const,
    startAngle: start,
    endAngle: end,
    min: opts.domainMin ?? 0,
    max,
    radius: `${outer - i * ((outer - inner) / Math.max(rows.length, 1))}%`,
    center: ["50%", "50%"],
    axisLine: { lineStyle: { color: [[1, r.color]], width: 18 } },
    progress: { show: false },
    pointer: { show: true, width: 3, itemStyle: { color: r.color } },
    detail: { show: !!opts.showLabels, formatter: (v: number) => `${r.name}: ${formatNumber(v, opts.yAxisFormat)}`, fontSize: 10, color: colorsForChart.text, offsetCenter: ["0%", `${(i - rows.length / 2) * 20}%`] },
    data: [{ value: r.value, name: r.name }],
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: { show: false },
    title: { show: false },
    animation: animate,
  }));

  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", formatter: (p: any) => `${p.name}: ${formatNumber(Number(p.value ?? 0), opts.yAxisFormat)}` },
    series,
    animation: animate,
  };
}

function buildTreemapOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  data: Row[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const groupKey = widget.chartSubtype === "nested" ? widget.groupByColumn : undefined;
  const treeData = prepareTreemapData(data, { nameKey: xKey, valueKey: yKey, groupKey });

  return {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "item", formatter: (p: any) => `${p.name}: ${formatNumber(Number(p.value ?? 0), opts.yAxisFormat)}` },
    series: [{
      type: "treemap" as const,
      data: treeData,
      label: { show: opts.showLabels !== false, fontSize: 10, color: isDark ? "#cbd5e1" : "#475569" },
      itemStyle: { borderColor: isDark ? "#0f172a" : "#fff", borderWidth: 1, gapWidth: 1 },
      breadcrumb: { show: false },
      animation: !!opts.animate,
    }],
    animation: !!opts.animate,
  };
}

function buildFunnelOption(
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

function buildSankeyOption(
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

function buildComboOption(
  widget: WidgetConfig,
  opts: VisualizationOptions,
  xKey: string,
  yKey: string,
  y2Key: string,
  chartData: Row[],
  seriesNames: string[],
  colors: string[],
  isDark: boolean
) {
  const tiny = !!opts.tinyMode;
  const sub = widget.chartSubtype ?? "";
  const showGrid = !tiny && opts.showGrid !== false;
  const showLegend = !tiny && opts.showLegend !== false;
  const colorsForChart = axisColors(isDark);
  const dualAxis = opts.dualAxis !== false;
  const animate = !!opts.animate;

  const categoryData = chartData.map((r) => String(r[xKey] ?? ""));
  const series: any[] = [];

  if (seriesNames.length >= 2 && (sub === "bar_line" || sub === "dual_line")) {
    // First series as bars, second as line
    const barName = seriesNames[0];
    const lineName = seriesNames[1];
    series.push({
      name: barName,
      type: "bar" as const,
      data: chartData.map((r) => toNumber(r[barName]) ?? 0),
      itemStyle: { color: colors[0] },
      label: { show: !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat) },
      yAxisIndex: 0,
      barMaxWidth: 40,
      animation: animate,
    });
    series.push({
      name: lineName,
      type: "line" as const,
      smooth: opts.curveType === "monotone",
      data: chartData.map((r) => toNumber(r[lineName]) ?? 0),
      itemStyle: { color: colors[1 % colors.length] },
      yAxisIndex: dualAxis ? 1 : 0,
      label: { show: !!opts.showLabels, position: "top", fontSize: 9, color: colorsForChart.text, formatter: (p: any) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat) },
      animation: animate,
    });
  } else if (y2Key) {
    series.push({
      name: yKey,
      type: "bar" as const,
      data: chartData.map((r) => toNumber(r[yKey]) ?? 0),
      itemStyle: { color: colors[0] },
      yAxisIndex: 0,
      barMaxWidth: 40,
      animation: animate,
    });
    const y2Values = chartData.map((r) => toNumber(r[y2Key]));
    if (y2Values.some((v) => v !== null)) {
      series.push({
        name: y2Key,
        type: "line" as const,
        smooth: opts.curveType === "monotone",
        data: y2Values,
        itemStyle: { color: colors[1 % colors.length] },
        yAxisIndex: 1,
        animation: animate,
      });
    }
  } else {
    // Fallback: bars from yKey and a line overlay from yKey
    series.push({
      name: yKey,
      type: "bar" as const,
      data: chartData.map((r) => toNumber(r[yKey]) ?? 0),
      itemStyle: { color: colors[0] },
      yAxisIndex: 0,
      barMaxWidth: 40,
      animation: animate,
    });
    series.push({
      name: `${yKey} (line)`,
      type: "line" as const,
      smooth: opts.curveType === "monotone",
      data: chartData.map((r) => toNumber(r[yKey]) ?? 0),
      itemStyle: { color: colors[1 % colors.length] },
      yAxisIndex: 0,
      animation: animate,
    });
  }

  const option: any = {
    aria: { enabled: true, description: `${widget.title || widget.type} chart` },
    color: colors,
    grid: commonGrid(tiny),
    tooltip: opts.showTooltip === false || tiny ? { show: false } : { trigger: "axis", formatter: (params: any) => tooltipFormatter(params, opts.yAxisFormat) },
    legend: showLegend ? getLegendConfig(opts, isDark) : undefined,
    xAxis: { type: "category" as const, data: categoryData, show: !tiny, axisLabel: { rotate: opts.xAxisLabelRotate ?? (categoryData.length > 8 ? -30 : 0), fontSize: 10, color: colorsForChart.text }, axisLine: { lineStyle: { color: colorsForChart.line } }, splitLine: { show: false } },
    yAxis: [
      { type: "value" as const, show: !tiny, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: showGrid ? { lineStyle: { color: colorsForChart.grid } } : undefined },
      ...(dualAxis && !tiny ? [{ type: "value" as const, show: true, position: "right" as const, axisLabel: { formatter: (v: number) => formatNumber(v, opts.yAxisFormat), fontSize: 10, color: colorsForChart.text }, splitLine: { show: false } }] : []),
    ],
    series,
    dataZoom: !tiny && opts.dataZoom ? [{ type: "inside" as const }, { type: "slider" as const, start: 0, end: 100, height: 16, bottom: 0 }] : undefined,
    animation: animate,
  };

  const markLineData = buildReferenceLines(opts.referenceLines);
  if (markLineData) option.series[0].markLine = { symbol: "none", data: markLineData };

  return option;
}

function tooltipFormatter(params: any, format?: string) {
  const rows = Array.isArray(params) ? params : [params];
  if (!rows.length) return "";
  const axis = rows[0].axisValueLabel ?? rows[0].name ?? "";
  return axis + rows.map((p: any) => `<br/>${p.marker} ${p.seriesName}: ${formatNumber(Number(p.value ?? 0), format)}`).join("");
}

function tooltipScatterFormatter(p: any, xKey: string, yKey: string, zKey: string, format?: string) {
  const vals = Array.isArray(p.value) ? p.value : [p.value];
  const x = vals[0];
  const y = vals[1];
  const z = vals[2];
  let s = `${xKey}: ${formatNumber(Number(x), format)}<br/>${yKey}: ${formatNumber(Number(y), format)}`;
  if (z !== undefined && zKey) s += `<br/>${zKey}: ${formatNumber(Number(z), format)}`;
  return s;
}

export function EChartsWidget({ widget, data, xKey, yKey, y2Key, chartData, seriesNames, onElementClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const echartsModuleRef = useRef<typeof echarts | null>(null);
  const isDark = useChartTheme();
  const { type, chartSubtype, visualizationOptions } = widget;
  const opts = useMemo(() => withDefaults(type, visualizationOptions), [type, visualizationOptions]);
  const palette = useMemo(() => getPalette(opts.colorScheme, isDark), [opts.colorScheme, isDark]);

  const sourceField = widget.interactions?.sourceField || widget.xColumn || xKey;

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let resizeHandler: (() => void) | null = null;

    const init = () => {
      if (disposed || !containerRef.current) return;
      const el = containerRef.current;
      const inVitest = typeof process !== "undefined" && process.env?.VITEST === "true";
      if (!inVitest && (el.clientWidth === 0 || el.clientHeight === 0)) return;

      let chart: any;
      try {
        chart = echarts.init(el, undefined, { renderer: "canvas" });
      } catch {
        // Zero-dimension container in test suites; ECharts is a no-op here.
        return;
      }
      chartRef.current = chart;
      echartsModuleRef.current = echarts;

      let option: any;
      try {
        switch (type) {
          case "line":
          case "area":
            option = buildLineOption(widget, opts, xKey, yKey, y2Key, chartData, seriesNames, palette, isDark);
            break;
          case "bar":
            option = buildBarOption(widget, opts, xKey, yKey, chartData, seriesNames, palette, isDark);
            break;
          case "pie":
            option = buildPieOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "combo":
            option = buildComboOption(widget, opts, xKey, yKey, y2Key, chartData, seriesNames, palette, isDark);
            break;
          case "scatter":
            option = buildScatterOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "radar":
            option = buildRadarOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "radial_bar":
            option = buildRadialBarOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "treemap":
            option = buildTreemapOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "funnel":
            option = buildFunnelOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "sankey":
            option = buildSankeyOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          default:
            option = { title: { text: "Unknown widget type", left: "center", top: "center" } };
        }
        chart.setOption(option, true);
      } catch {
        try { chart.dispose(); } catch {}
        return;
      }

      if (onElementClick && type !== "kpi" && type !== "table") {
        chart.on("click", (params: any) => {
          let value: string | number = "";
          let label = "";
          if (["line", "bar", "area", "combo"].includes(type)) {
            value = params.name ?? "";
            label = `${sourceField}: ${value}`;
          } else if (type === "scatter") {
            const arr = Array.isArray(params.value) ? params.value : [params.value];
            value = arr[0] ?? "";
            label = `${sourceField}: ${value}`;
          } else {
            value = params.name ?? "";
            label = `${sourceField}: ${value}`;
          }
          onElementClick({ sourceField, value, label });
        });
      }

      const handleResize = () => chart.resize();
      resizeHandler = handleResize;
      window.addEventListener("resize", handleResize);

      if (typeof ResizeObserver !== "undefined" && !inVitest) {
        resizeObserver = new ResizeObserver(() => chart.resize());
        try {
          resizeObserver.observe(el);
        } catch {}
      }
    };

    init();

    return () => {
      disposed = true;
      if (resizeHandler) window.removeEventListener("resize", resizeHandler);
      if (resizeObserver) {
        try { resizeObserver.disconnect(); } catch {}
      }
      if (chartRef.current) {
        try { chartRef.current.dispose(); } catch {}
        chartRef.current = null;
      }
    };
  }, [widget, data, type, chartSubtype, xKey, yKey, y2Key, chartData, seriesNames, onElementClick, opts, palette, isDark, sourceField]);

  if (data.length === 0) return <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">No data</div>;

  return (
    <div className="h-full w-full">
      <div
        ref={containerRef}
        data-testid="echarts-widget"
        data-chart-renderer="echarts"
        className="h-full w-full"
        aria-label={`${widget.title || type} chart`}
      />
      <table className="sr-only">
        <caption>{widget.title || `${type} chart`}</caption>
        <thead>
          <tr>{data.length > 0 ? Object.keys(data[0]).map((k) => <th key={k}>{k}</th>) : null}</tr>
        </thead>
        <tbody>
          {data.slice(0, 50).map((row, i) => (
            <tr key={i}>{Object.keys(data[0] ?? {}).map((k) => <td key={k}>{String(row[k] ?? "")}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
