"use client";

import { useEffect, useRef } from "react";
import type { ItsmChart } from "./types";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  TitleComponent,
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
  TitleComponent,
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
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const instance = echarts.init(containerRef.current, undefined, { renderer: "canvas" });
    chartRef.current = instance;

    const data = chart.series[0]?.y ?? [];
    const categories = chart.categories.length ? chart.categories : chart.series[0]?.x ?? [];

    let option: echarts.EChartsCoreOption;

    if (chart.chartType === "pie" || chart.chartType === "doughnut") {
      const pieData = categories.map((name, i) => ({ name, value: data[i] ?? 0 }));
      option = {
        title: { text: chart.title, left: "center", textStyle: { fontSize: 13 } },
        tooltip: { trigger: "item" },
        legend: { bottom: 0, type: "scroll" },
        series: [
          {
            type: "pie",
            radius: ["40%", "70%"],
            data: pieData,
            emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.2)" } },
          },
        ],
      };
    } else {
      const type = chart.chartType === "line" ? "line" : "bar";
      option = {
        title: { text: chart.title, left: "left", textStyle: { fontSize: 13 } },
        tooltip: { trigger: "axis" },
        grid: { left: "3%", right: "4%", bottom: "12%", top: "18%", containLabel: true },
        xAxis: {
          type: "category",
          data: categories,
          axisLabel: { interval: 0, rotate: categories.length > 8 ? 45 : 0, fontSize: 11 },
        },
        yAxis: { type: "value", name: chart.yAxisLabel ?? undefined },
        series: [
          {
            type,
            data: data.map((v) => (v === null ? 0 : v)),
            itemStyle: { borderRadius: type === "bar" ? [4, 4, 0, 0] : undefined },
            smooth: true,
          },
        ],
      };
    }

    instance.setOption(option, true);

    if (onElementClick) {
      instance.on("click", (params) => {
        if (params && typeof params.name === "string") {
          onElementClick(params.name, typeof params.value === "number" ? params.value : null);
        }
      });
    }

    const handleResize = () => instance.resize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      instance.dispose();
      chartRef.current = null;
    };
  }, [chart, onElementClick]);

  return <div ref={containerRef} className={cn("h-72 w-full", className)} />;
}
