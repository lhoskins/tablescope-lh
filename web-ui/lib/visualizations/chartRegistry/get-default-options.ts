/**
 * Central chart registry.
 *
 * A single source of truth describing each chart family: the variants it
 * supports, the option fields the editor should expose, default option
 * values, the fields it requires, and the AI selection rules. The dashboard
 * widget editor, the option panel, config validation, and AI dashboard
 * generation all read from this registry so the chart catalog stays
 * consistent and easy to extend.
 */

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { getChartDefinition } from "./get-chart-definition";



/** Builds the default options object for a chart type from the registry. */
export function getDefaultOptions(type: string): VisualizationOptions {
  const def = getChartDefinition(type);
  if (!def) return {};
  const out: Record<string, unknown> = {};
  for (const opt of def.options) {
    if (opt.defaultValue !== undefined) out[opt.key] = opt.defaultValue;
  }
  return out as VisualizationOptions;
}