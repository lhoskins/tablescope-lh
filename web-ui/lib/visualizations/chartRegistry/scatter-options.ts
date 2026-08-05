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
import { Y_AXIS_FORMAT_OPTION } from "./y-axis-format-option";
import { DATA_ZOOM_OPTION } from "./data-zoom-option";



export const SCATTER_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showGrid", label: "Show grid", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show point labels", type: "boolean", group: "chart", defaultValue: false },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  DATA_ZOOM_OPTION,
  { key: "bubble", label: "Bubble (size by Z)", type: "boolean", group: "chart", defaultValue: false, description: "Sizes each point by the Z column." },
  { key: "showTrendLine", label: "Line of best fit", type: "boolean", group: "advanced", defaultValue: false },
];