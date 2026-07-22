"use client";

import { useEffect, useRef, useMemo } from "react";
import type { ChartClickEvent, WidgetConfig, VisualizationOptions } from "./types";
import { withDefaults } from "@/lib/visualizations/chartRegistry";

type Props = {
  widget: WidgetConfig;
  data: Array<Record<string, unknown>>;
  xKey: string;
  yKey: string;
  y2Key: string;
  chartData: Array<Record<string, unknown>>;
  seriesNames: string[];
  onElementClick?: (event: ChartClickEvent) => void;
};

function fmtNumber(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtAxis(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

const COLORS = [
  "#3b82f6", "#8b5cf6", "#ec4899", "#10b981", "#f59e0b",
  "#ef4444", "#06b6d4", "#6366f1", "#84cc16", "#f97316",
];

function isNumeric(v: unknown): boolean {
  return typeof v === "number" || (typeof v === "string" && v !== "" && !isNaN(Number(v.replace(/[,$%]/g, ""))));
}

function toNumber(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number(v.replace(/[,$%]/g, ""));
    return isNaN(n) ? null : n;
  }
  return null;
}

function buildLineOption(chartSubtype: string | undefined, opts: VisualizationOptions, xKey: string, yKey: string, chartData: Array<Record<string, unknown>>, seriesNames: string[]) {
  const showGrid = opts.showGrid !== false;
  const showLegend = !!opts.showLegend && seriesNames.length > 0;
  const showDots = !!opts.showDots;
  const connectNulls = !!opts.connectNulls;
  const smooth = opts.curveType === "monotone" || (!opts.curveType && chartSubtype === "smooth_line");
  const step = opts.curveType === "step" ? "middle" as const : undefined;

  const names = seriesNames.length > 0 ? seriesNames : [yKey];
  const series = names.map((name, i) => ({
    name,
    type: "line" as const,
    smooth,
    step,
    connectNulls,
    showSymbol: showDots,
    data: chartData.map((row) => toNumber(row[name]) ?? null),
    itemStyle: { color: COLORS[i % COLORS.length] },
    lineStyle: { width: 2.5, type: opts.lineStyle === "dashed" ? "dashed" as const : "solid" as const },
  }));

  return {
    grid: { top: 24, right: 20, bottom: 30, left: 46 },
    tooltip: { trigger: "axis" as const, formatter: (params: any) => {
      const rows = Array.isArray(params) ? params : [params];
      return `${rows[0]?.axisValueLabel ?? ""}<br/>` + rows.map((p: any) => `${p.marker} ${p.seriesName}: ${fmtNumber(Number(p.value ?? 0))}`).join("<br/>");
    }},
    legend: showLegend ? { bottom: 0, textStyle: { fontSize: 11 } } : undefined,
    xAxis: { type: "category" as const, data: chartData.map((row) => String(row[xKey] ?? "")), axisLabel: { rotate: chartData.length > 8 ? -30 : 0, fontSize: 10 }, axisLine: { lineStyle: { color: "#cbd5e1" } } },
    yAxis: { type: "value" as const, axisLabel: { formatter: (v: number) => fmtAxis(v), fontSize: 10 }, splitLine: showGrid ? { lineStyle: { color: "#f1f5f9" } } : undefined },
    series,
    animation: !!opts.animate,
  };
}

function buildBarOption(chartSubtype: string | undefined, opts: VisualizationOptions, xKey: string, yKey: string, chartData: Array<Record<string, unknown>>, seriesNames: string[]) {
  const showGrid = opts.showGrid !== false;
  const showLegend = !!opts.showLegend && seriesNames.length > 0;
  const horizontal = opts.barLayout === "horizontal" || chartSubtype === "horizontal_bar" || chartSubtype === "stacked_horizontal";
  const stack = opts.stackMode === "stacked" || opts.stackMode === "percent" ? "total" : undefined;
  const percent = opts.stackMode === "percent";

  const names = seriesNames.length > 0 ? seriesNames : [yKey];
  const series = names.map((name, i) => ({
    name,
    type: "bar" as const,
    stack,
    data: chartData.map((row) => {
      const v = toNumber(row[name]) ?? 0;
      return percent && names.length > 0 ? Number((v * 100).toFixed(2)) : v;
    }),
    itemStyle: { color: COLORS[i % COLORS.length] },
    barMaxWidth: 48,
  }));

  return {
    grid: { top: 24, right: 20, bottom: 30, left: horizontal ? 80 : 46 },
    tooltip: { trigger: "axis" as const, formatter: (params: any) => {
      const rows = Array.isArray(params) ? params : [params];
      return `${rows[0]?.axisValueLabel ?? ""}<br/>` + rows.map((p: any) => `${p.marker} ${p.seriesName}: ${fmtNumber(Number(p.value ?? 0))}${percent ? "%" : ""}`).join("<br/>");
    }},
    legend: showLegend ? { bottom: 0, textStyle: { fontSize: 11 } } : undefined,
    xAxis: horizontal ? { type: "value" as const, axisLabel: { formatter: (v: number) => fmtAxis(v), fontSize: 10 }, splitLine: showGrid ? { lineStyle: { color: "#f1f5f9" } } : undefined } : { type: "category" as const, data: chartData.map((row) => String(row[xKey] ?? "")), axisLabel: { rotate: chartData.length > 8 ? -30 : 0, fontSize: 10 }, axisLine: { lineStyle: { color: "#cbd5e1" } } },
    yAxis: horizontal ? { type: "category" as const, data: chartData.map((row) => String(row[xKey] ?? "")), axisLabel: { fontSize: 10 }, axisLine: { lineStyle: { color: "#cbd5e1" } } } : { type: "value" as const, axisLabel: { formatter: (v: number) => fmtAxis(v), fontSize: 10 }, splitLine: showGrid ? { lineStyle: { color: "#f1f5f9" } } : undefined },
    series,
    animation: !!opts.animate,
  };
}

function buildPieOption(chartSubtype: string | undefined, opts: VisualizationOptions, xKey: string, yKey: string, chartData: Array<Record<string, unknown>>) {
  const donut = opts.innerRadius !== undefined ? opts.innerRadius > 0 : chartSubtype === "donut";
  const data = chartData.map((row) => ({ name: String(row[xKey] ?? ""), value: toNumber(row[yKey]) ?? 0 }));
  return {
    tooltip: { trigger: "item" as const, formatter: (params: any) => `${params.name}: ${fmtNumber(Number(params.value ?? 0))} (${params.percent}%)` },
    legend: opts.showLegend !== false ? { bottom: 0, textStyle: { fontSize: 11 } } : undefined,
    series: [{
      type: "pie" as const,
      radius: donut ? ["40%", "70%"] : "70%",
      data,
      itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 1 },
      label: { show: opts.showLabels !== false, fontSize: 10 },
      animation: !!opts.animate,
    }],
  };
}

export function EChartsWidget({ widget, data, xKey, yKey, chartData, seriesNames, onElementClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const echartsRef = useRef<any>(null);
  const { type, chartSubtype, visualizationOptions } = widget;
  const opts = useMemo(() => withDefaults(type, visualizationOptions), [type, visualizationOptions]);

  const buildOption = useMemo(() => {
    switch (type) {
      case "line":
      case "area":
        return () => buildLineOption(chartSubtype, opts, xKey, yKey, chartData, seriesNames);
      case "bar":
        return () => buildBarOption(chartSubtype, opts, xKey, yKey, chartData, seriesNames);
      case "pie":
        return () => buildPieOption(chartSubtype, opts, xKey, yKey, chartData);
      default:
        return null;
    }
  }, [type, chartSubtype, opts, xKey, yKey, chartData, seriesNames]);

  useEffect(() => {
    if (!containerRef.current || !buildOption) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;

    const inVitest = typeof process !== "undefined" && process.env?.VITEST === "true";

    const renderChart = () => {
      if (!echartsRef.current || !containerRef.current) return;
      if (chartRef.current) {
        chartRef.current.setOption(buildOption(), true);
        return;
      }
      const el = containerRef.current;
      if (!inVitest && (el.clientWidth === 0 || el.clientHeight === 0)) return;
      const chart = echartsRef.current.init(el, undefined, { renderer: "canvas" });
      chartRef.current = chart;
      chart.setOption(buildOption(), true);
      if (onElementClick) {
        chart.on("click", (params: any) => {
          onElementClick({
            sourceField: params.seriesName || xKey,
            value: params.name ?? params.value ?? "",
            label: String(params.name ?? ""),
          });
        });
      }
    };

    const handleResize = () => {
      if (chartRef.current) chartRef.current.resize();
    };

    const init = async () => {
      echartsRef.current = await import("echarts");
      if (!disposed) renderChart();
    };

    init();

    window.addEventListener("resize", handleResize);

    if (typeof ResizeObserver !== "undefined" && containerRef.current) {
      resizeObserver = new ResizeObserver(() => {
        if (chartRef.current) chartRef.current.resize();
        else renderChart();
      });
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      disposed = true;
      window.removeEventListener("resize", handleResize);
      if (resizeObserver) {
        try {
          resizeObserver.disconnect();
        } catch {
          /* ignore */
        }
      }
      try {
        if (chartRef.current) {
          chartRef.current.dispose();
          chartRef.current = null;
        }
      } catch {
        /* ignore in environments without a real canvas */
      }
    };
  }, [buildOption, onElementClick, xKey]);

  if (data.length === 0) return <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">No data</div>;

  return (
    <div
      ref={containerRef}
      data-testid="echarts-widget"
      data-chart-renderer="echarts"
      className="h-full w-full"
    />
  );
}
