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
import { COLOR_SCHEME_OPTION } from "./color-scheme-option";
import { LEGEND_POSITION_OPTION } from "./legend-position-option";



export const FUNNEL_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLabels", label: "Show labels", type: "boolean", group: "chart", defaultValue: true },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: false },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
];