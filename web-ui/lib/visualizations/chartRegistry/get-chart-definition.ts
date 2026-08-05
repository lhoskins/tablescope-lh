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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { ChartTypeDefinition } from "./chart-type-definition";
import { CHART_REGISTRY } from "./chart-registry";



/** Returns the registry definition for a chart type, or undefined. */
export function getChartDefinition(type: string): ChartTypeDefinition | undefined {
  return CHART_REGISTRY[type as WidgetType];
}