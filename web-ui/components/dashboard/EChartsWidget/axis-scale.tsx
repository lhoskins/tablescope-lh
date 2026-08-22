import type { VisualizationOptions } from "../types";
import { formatNumber } from "./format-number";

const SCALE_FACTORS = {
  none: 1,
  thousands: 1_000,
  millions: 1_000_000,
  billions: 1_000_000_000,
} as const;

/**
 * Axis tick formatter honouring the chart's *display unit*.
 *
 * `yAxisScale` is the Excel-style "display units" setting: it divides only the
 * rendered tick labels (so a 6,899,318.98 axis reads "6,899" against a
 * "Thousands" axis name) and never touches the query or the underlying raw
 * values.
 *
 * `valueScale` is the separate, pre-existing per-chart unit override coming
 * from the designer's "Specific charts" picker, which suffixes each tick
 * (K/M/H) instead of naming the axis. When an explicit `yAxisScale` display
 * unit is in play the axis name already communicates the unit, so the suffix
 * is dropped to avoid stating (and dividing by) the unit twice. With no
 * display unit selected -- the default -- this is exactly the previous
 * `formatNumber(v, yAxisFormat, valueScale)` behaviour.
 */
export function formatAxisNumber(value: number, options: VisualizationOptions): string {
  const scale = options.yAxisScale ?? "none";
  if (scale === "none") return formatNumber(value, options.yAxisFormat, options.valueScale);
  return formatNumber(value / SCALE_FACTORS[scale], options.yAxisFormat);
}

export function axisScaleLabel(options: VisualizationOptions): string | undefined {
  const scale = options.yAxisScale ?? "none";
  if (scale === "none") return undefined;
  return scale[0].toUpperCase() + scale.slice(1);
}
