"use client";

import { useEffect, useRef } from "react";
import type { ItsmChart } from "./types";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  AriaComponent,
  DatasetComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { cn } from "@/lib/cn";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  AriaComponent,
  DatasetComponent,
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
    } else if (chart.chartType === "bar") {
      option = {
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        grid: { left: 8, right: 42, bottom: 8, top: 8, containLabel: true },
        xAxis: {
          type: "value",
          name: chart.yAxisLabel ?? undefined,
          nameGap: 10,
          splitLine: { lineStyle: { color: "#e8edf3" } },
        },
        yAxis: {
          type: "category",
          inverse: true,
          data: categories,
          axisTick: { show: false },
          axisLabel: { width: 126, overflow: "truncate", fontSize: 11 },
        },
        series: [
          {
            type: "bar",
            data,
            barMaxWidth: 16,
            itemStyle: { color: "#4f7cff", borderRadius: [0, 5, 5, 0] },
            label: { show: true, position: "right", fontSize: 10, color: "#475569" },
          },
        ],
      };
    } else {
      option = {
        tooltip: { trigger: "axis" },
        grid: { left: 10, right: 16, bottom: 12, top: 12, containLabel: true },
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
        },
        series: [
          {
            type: "line",
            data,
            smooth: true,
            symbolSize: 6,
            connectNulls: false,
            lineStyle: { width: 2, color: "#3b82f6" },
            itemStyle: { color: "#3b82f6" },
            areaStyle: { color: "rgba(59, 130, 246, 0.12)" },
          },
        ],
      };
    }

    instance.setOption(option, true);
    if (onElementClick) {
      instance.on("click", (params) => {
        if (params && typeof params.name === "string") {
          const rawValue = Array.isArray(params.value) ? params.value[params.value.length - 1] : params.value;
          onElementClick(params.name, typeof rawValue === "number" ? rawValue : null);
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
