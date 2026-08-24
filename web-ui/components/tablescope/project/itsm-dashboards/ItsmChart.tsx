"use client";

import { useEffect, useRef } from "react";
import type { ItsmChart } from "./types";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  AriaComponent,
  DatasetComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { cn } from "@/lib/cn";
import { OPERATIONAL_INSIGHT_THEME } from "@/components/dashboard/operational-insight-theme";
import { formatNumber } from "@/components/dashboard/EChartsWidget/format-number";
import { formatAxisNumber } from "@/components/dashboard/EChartsWidget/axis-scale";
import { tooltipFormatter } from "@/components/dashboard/EChartsWidget/tooltip-formatter";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  HeatmapChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  AriaComponent,
  DatasetComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export interface ItsmChartProps {
  chart: ItsmChart;
  onElementClick?: (name: string, value: number | null) => void;
  className?: string;
}

export function ItsmChart({ chart, onElementClick, className }: ItsmChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const instance = echarts.init(containerRef.current, undefined, { renderer: "canvas" });
    const data = chart.series[0]?.y ?? [];
    const categories = chart.categories.length ? chart.categories : chart.series[0]?.x ?? [];
    // Only set for AI-Designer widgets (see toOperationalChartData) -- kept
    // undefined for the ITSM presets so their existing (unformatted-count)
    // axis/label rendering is unchanged.
    const opts = chart.visualizationOptions;

    let option: echarts.EChartsCoreOption;
    if (chart.chartType === "pie" || chart.chartType === "doughnut") {
      option = {
        tooltip: { trigger: "item" },
        legend: { bottom: 0, type: "scroll" },
        series: [
          {
            type: "pie",
            radius: ["44%", "72%"],
            data: categories.map((name, index) => ({ name, value: data[index] })),
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.18)" } },
          },
        ],
      };
    } else if (chart.chartType === "heatmap") {
      const heatData = chart.series.flatMap((series, seriesIndex) =>
        series.y.map((value, categoryIndex) => [categoryIndex, seriesIndex, value ?? 0]),
      );
      const maximum = Math.max(1, ...heatData.map((item) => Number(item[2] ?? 0)));
      option = {
        tooltip: {
          position: "top",
          formatter: (params: unknown) => {
            const point = params as { value?: unknown[] };
            const value = point.value ?? [];
            const category = categories[Number(value[0])] ?? "Status";
            const series = chart.series[Number(value[1])]?.name ?? "Priority";
            return `${series} · ${category}<br/><strong>${Number(value[2] ?? 0).toLocaleString()}</strong>`;
          },
        },
        grid: { left: 8, right: 12, bottom: 8, top: 8, containLabel: true },
        xAxis: { type: "category", data: categories, splitArea: { show: true }, axisTick: { show: false } },
        yAxis: { type: "category", data: chart.series.map((series) => series.name), splitArea: { show: true }, axisTick: { show: false } },
        visualMap: { min: 0, max: maximum, show: false, inRange: { color: ["#eff6ff", "#93c5fd", "#2563eb"] } },
        series: [{ type: "heatmap", data: heatData, label: { show: true, fontSize: 10 }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(15, 23, 42, 0.18)" } } }],
      };
    } else if (chart.chartType === "column") {
      // Vertical bars -- the axes are swapped relative to "bar"/"skinny_bar"
      // below, which are both horizontal. Distinct from those two so a
      // widget explicitly configured as a vertical bar (chartSubtype other
      // than a horizontal variant) renders that way here too, instead of
      // this renderer silently forcing every bar horizontal.
      option = {
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          ...(opts ? { formatter: (params: unknown) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale, opts.currencySymbol) } : {}),
        },
        grid: { left: 8, right: 12, bottom: 8, top: 8, containLabel: true },
        xAxis: {
          type: "category",
          data: categories,
          axisTick: { show: false },
          axisLabel: { fontSize: 11 },
        },
        yAxis: {
          type: "value",
          name: chart.yAxisLabel ?? undefined,
          nameGap: 10,
          splitLine: { lineStyle: { color: "#e8edf3" } },
          ...(opts ? { axisLabel: { formatter: (v: number) => formatAxisNumber(v, opts) } } : {}),
        },
        series: chart.series.map((series, index) => ({
          type: "bar",
          name: series.name,
          data: series.y,
          barMaxWidth: 32,
          itemStyle: {
            color: OPERATIONAL_INSIGHT_THEME.palette[index % OPERATIONAL_INSIGHT_THEME.palette.length],
            borderRadius: [4, 4, 0, 0],
          },
          label: {
            show: true,
            position: "top",
            fontSize: 10,
            color: "#475569",
            ...(opts ? { formatter: (p: { value?: unknown }) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat, opts.valueScale, opts.currencySymbol) } : {}),
          },
        })),
      };
    } else if (chart.chartType === "bar" || chart.chartType === "skinny_bar") {
      option = {
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          ...(opts ? { formatter: (params: unknown) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale, opts.currencySymbol) } : {}),
        },
        grid: { left: 8, right: 42, bottom: 8, top: 8, containLabel: true },
        xAxis: {
          type: "value",
          name: chart.chartType === "skinny_bar" ? undefined : chart.yAxisLabel ?? undefined,
          nameGap: 10,
          splitLine: { lineStyle: { color: "#e8edf3" } },
          ...(opts ? { axisLabel: { formatter: (v: number) => formatAxisNumber(v, opts) } } : {}),
        },
        yAxis: {
          type: "category",
          inverse: true,
          data: categories,
          axisTick: { show: false },
          axisLabel: { width: 126, overflow: "truncate", fontSize: 11 },
        },
        series: chart.series.map((series, index) => ({
          type: "bar",
          name: series.name,
          data: series.y,
          barMaxWidth: chart.chartType === "skinny_bar" ? 10 : 16,
          itemStyle: { color: OPERATIONAL_INSIGHT_THEME.palette[index % OPERATIONAL_INSIGHT_THEME.palette.length], borderRadius: [0, 5, 5, 0] },
          label: {
            show: true,
            position: "right",
            fontSize: 10,
            color: "#475569",
            ...(opts ? { formatter: (p: { value?: unknown }) => formatNumber(Number(p.value ?? 0), opts.yAxisFormat, opts.valueScale, opts.currencySymbol) } : {}),
          },
        })),
      };
    } else if (chart.chartType === "combo" && chart.series.length >= 2) {
      // Two-metric comparison (e.g. actual vs backlog over time): first
      // series as bars, second as an overlaid line -- mirrors
      // EChartsWidget's buildComboOption so an AI-Designer combo widget
      // looks the same whether it renders through the generic dashboard
      // grid or this operational-insight one.
      option = {
        tooltip: {
          trigger: "axis",
          ...(opts ? { formatter: (params: unknown) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale, opts.currencySymbol) } : {}),
        },
        legend: { top: 0, right: 4 },
        grid: { left: 10, right: 16, bottom: 12, top: 34, containLabel: true },
        xAxis: {
          type: "category",
          boundaryGap: true,
          data: categories,
          axisTick: { show: false },
          axisLabel: { interval: Math.max(0, Math.ceil(categories.length / 7) - 1), fontSize: 10 },
        },
        yAxis: {
          type: "value",
          name: chart.yAxisLabel ?? undefined,
          nameGap: 12,
          splitLine: { lineStyle: { color: "#e8edf3" } },
          ...(opts ? { axisLabel: { formatter: (v: number) => formatAxisNumber(v, opts) } } : {}),
        },
        series: [
          {
            type: "bar",
            name: chart.series[0].name,
            data: chart.series[0].y,
            barMaxWidth: 24,
            itemStyle: { color: OPERATIONAL_INSIGHT_THEME.palette[0], borderRadius: [4, 4, 0, 0] },
          },
          {
            type: "line",
            name: chart.series[1].name,
            data: chart.series[1].y,
            smooth: true,
            symbolSize: 6,
            connectNulls: false,
            lineStyle: { width: 2, color: OPERATIONAL_INSIGHT_THEME.palette[1 % OPERATIONAL_INSIGHT_THEME.palette.length] },
            itemStyle: { color: OPERATIONAL_INSIGHT_THEME.palette[1 % OPERATIONAL_INSIGHT_THEME.palette.length] },
          },
        ],
      };
    } else {
      option = {
        tooltip: {
          trigger: "axis",
          ...(opts ? { formatter: (params: unknown) => tooltipFormatter(params, opts.yAxisFormat, opts.valueScale, opts.currencySymbol) } : {}),
        },
        legend: chart.series.length > 1 ? { top: 0, right: 4 } : undefined,
        grid: { left: 10, right: 16, bottom: 12, top: chart.series.length > 1 ? 34 : 12, containLabel: true },
        xAxis: {
          type: "category",
          boundaryGap: false,
          data: categories,
          axisTick: { show: false },
          axisLabel: { interval: Math.max(0, Math.ceil(categories.length / 7) - 1), fontSize: 10 },
        },
        yAxis: {
          type: "value",
          name: chart.yAxisLabel ?? undefined,
          nameGap: 12,
          splitLine: { lineStyle: { color: "#e8edf3" } },
          ...(opts ? { axisLabel: { formatter: (v: number) => formatAxisNumber(v, opts) } } : {}),
        },
        series: chart.series.map((series, index) => ({
          type: "line",
          name: series.name,
          data: series.y,
          smooth: true,
          symbolSize: 6,
          connectNulls: false,
          lineStyle: { width: 2, color: OPERATIONAL_INSIGHT_THEME.palette[index % OPERATIONAL_INSIGHT_THEME.palette.length] },
          itemStyle: { color: OPERATIONAL_INSIGHT_THEME.palette[index % OPERATIONAL_INSIGHT_THEME.palette.length] },
          areaStyle: index === 0 ? { color: "rgba(59, 130, 246, 0.10)" } : undefined,
        })),
      };
    }

    instance.setOption(option, true);
    if (onElementClick) {
      instance.on("click", (params) => {
        if (params) {
          const rawValue = Array.isArray(params.value) ? params.value[params.value.length - 1] : params.value;
          const name = chart.chartType === "heatmap" && Array.isArray(params.value)
            ? `${chart.series[Number(params.value[1])]?.name ?? "Priority"} · ${categories[Number(params.value[0])] ?? "Status"}`
            : typeof params.name === "string" ? params.name : "Selection";
          onElementClick(name, typeof rawValue === "number" ? rawValue : null);
        }
      });
    }

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => instance.resize());
    observer?.observe(containerRef.current);
    const handleWindowResize = () => instance.resize();
    if (!observer) window.addEventListener("resize", handleWindowResize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", handleWindowResize);
      instance.dispose();
    };
  }, [chart, onElementClick]);

  return <div ref={containerRef} className={cn("h-56 w-full", className)} />;
}
