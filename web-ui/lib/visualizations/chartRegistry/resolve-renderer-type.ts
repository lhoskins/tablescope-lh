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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { CHART_REGISTRY } from "./chart-registry";



/** Resolves a chart type to a renderer key, falling back to "table". */
export function resolveRendererType(type: string): WidgetType {
  return CHART_REGISTRY[type as WidgetType] ? (type as WidgetType) : "table";
}