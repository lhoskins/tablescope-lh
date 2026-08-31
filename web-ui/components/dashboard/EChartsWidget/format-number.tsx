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
import { CanvasRenderer } from "echarts/renderers";


export type ValueScale = "auto" | "hundreds" | "thousands" | "millions";

const SCALE_DIVISORS: Record<Exclude<ValueScale, "auto">, number> = {
  hundreds: 100,
  thousands: 1_000,
  millions: 1_000_000,
};
const SCALE_SUFFIXES: Record<Exclude<ValueScale, "auto">, string> = {
  hundreds: "H",
  thousands: "K",
  millions: "M",
};

/**
 * `scale` forces the display unit (e.g. always show a $-millions axis even
 * for a metric that dips under $1M) instead of the auto K/M breakpoints
 * `format: "currency"|"compact"` already apply based on each value's own
 * magnitude. Left at "auto" (or omitted), behavior is unchanged. Percent
 * values are never rescaled -- a forced scale on a 0-100% axis would be
 * meaningless.
 *
 * `currencySymbol` is the symbol shown for `format: "currency"` (e.g. "$",
 * "€"), set from the dashboard's selected currency. Defaults to "$" so
 * every existing call site (and every saved dashboard predating currency
 * selection) renders unchanged.
 */
export function formatNumber(v: number, format?: string, scale?: ValueScale, currencySymbol = "$"): string {
  if (!Number.isFinite(v)) return "—";
  if (format === "percent") return `${(v * 100).toFixed(2)}%`;
  if (scale && scale !== "auto") {
    const scaled = v / SCALE_DIVISORS[scale];
    const prefix = format === "currency" ? currencySymbol : "";
    return `${prefix}${scaled.toLocaleString(undefined, { maximumFractionDigits: 1 })}${SCALE_SUFFIXES[scale]}`;
  }
  if (format === "currency") {
    if (Math.abs(v) >= 1_000_000) return `${currencySymbol}${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `${currencySymbol}${(v / 1_000).toFixed(0)}K`;
    return `${currencySymbol}${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  }
  if (format === "compact") {
    if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  }
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/**
 * Picks a single shared display unit (millions/thousands/none) for a whole
 * chart's worth of values, based on the largest magnitude among them --
 * e.g. a "revenue by customer" bar chart with every value in the tens of
 * millions gets one consistent "M" axis, not a per-tick guess. Callers
 * resolve this once, at widget-build time, and set the concrete result as
 * `visualizationOptions.valueScale` -- this intentionally does not reuse
 * the `"auto"` `ValueScale` member, which is documented (and tested) to mean
 * "no forced scale, same as omitted" for designer-configured charts.
 */
export function autoValueScale(
  values: Array<number | null | undefined>,
): Exclude<ValueScale, "auto"> | undefined {
  let max = 0;
  for (const v of values) {
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    const abs = Math.abs(v);
    if (abs > max) max = abs;
  }
  if (max >= 1_000_000) return "millions";
  if (max >= 1_000) return "thousands";
  return undefined;
}

/**
 * Full-precision rendering for tooltips: the exact value, thousands
 * separators, always two decimal places ("cents") -- regardless of any
 * axis-display scale (K/M) applied to the same value's tick/bar label.
 * Percent is capped at two decimals like every other percent display
 * (see `formatNumber`'s `percent` branch); it has no "cents" concept.
 */
export function formatFullPrecision(v: number, format?: string, currencySymbol = "$"): string {
  if (!Number.isFinite(v)) return "—";
  if (format === "percent") return `${(v * 100).toFixed(2)}%`;
  const prefix = format === "currency" ? currencySymbol : "";
  return `${prefix}${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}