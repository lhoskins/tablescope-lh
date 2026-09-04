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
  CalendarComponent,
} from "echarts/components";
import { LegacyGridContainLabel } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";import { EChartsType } from "./EChartsWidget/echarts-type";
import { Props } from "./EChartsWidget/props";
import { getPalette } from "./EChartsWidget/get-palette";
import { useChartTheme } from "./EChartsWidget/use-chart-theme";
import { buildLineOption, buildBarOption, buildPieOption, buildScatterOption, buildHeatmapOption, buildRadarOption, buildRadialBarOption, buildTreemapOption, buildFunnelOption, buildSankeyOption, buildComboOption, buildGaugeOption, buildPictorialBarOption, buildSunburstOption, buildTreeOption, buildGraphOption, buildParallelOption, buildLinesOption, buildBoxplotOption, buildThemeRiverOption, buildCandlestickOption, buildMapOption } from "./EChartsWidget/echarts-option-builders";



// Tree-shaken ECharts modules — only these are bundled.
echarts.use([
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
  CalendarComponent,
  LegacyGridContainLabel,
  CanvasRenderer,
]);

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
      } catch (error) {
        // Keep the card alive, but make real initialization failures visible.
        if (!inVitest) console.error("ECharts initialization failed", error);
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
          case "effect_scatter":
            option = buildScatterOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "heatmap":
            option = buildHeatmapOption(widget, opts, xKey, yKey, data, palette, isDark);
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
          case "gauge":
            option = buildGaugeOption(widget, opts, yKey, data, palette, isDark);
            break;
          case "pictorial_bar":
            option = buildPictorialBarOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "sunburst":
            option = buildSunburstOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "tree":
            option = buildTreeOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "graph":
            option = buildGraphOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "parallel":
            option = buildParallelOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "lines":
            option = buildLinesOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "boxplot":
            option = buildBoxplotOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "theme_river":
            option = buildThemeRiverOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "candlestick":
            option = buildCandlestickOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          case "map":
            option = buildMapOption(widget, opts, xKey, yKey, data, palette, isDark);
            break;
          default:
            option = { title: { text: "Unknown widget type", left: "center", top: "center" } };
        }
        chart.setOption(option, true);
      } catch (error) {
        console.error("ECharts option rendering failed", {
          type,
          chartSubtype,
          error,
        });
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
      <div className="sr-only">
        <table>
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
    </div>
  );
}
