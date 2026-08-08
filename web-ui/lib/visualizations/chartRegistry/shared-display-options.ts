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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { ChartOptionDefinition } from "./chart-option-definition";



export const SHARED_DISPLAY_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show data labels", type: "boolean", group: "chart", defaultValue: false },
  { key: "showGrid", label: "Show grid", type: "boolean", group: "chart", defaultValue: true },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  { key: "tinyMode", label: "Tiny (sparkline) mode", type: "boolean", group: "style", defaultValue: false },
];