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
import { X_AXIS_ROTATE_OPTION } from "./x-axis-rotate-option";
import { Y_AXIS_FORMAT_OPTION } from "./y-axis-format-option";
import { DATA_ZOOM_OPTION } from "./data-zoom-option";
import { SHARED_DISPLAY_OPTIONS } from "./shared-display-options";



export const BAR_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
  { key: "showControlLimits", label: "Show control limits (±2σ)", type: "boolean", group: "advanced", defaultValue: false },
  {
    key: "barLayout",
    label: "Orientation",
    type: "select",
    group: "chart",
    defaultValue: "vertical",
    options: [
      { label: "Vertical bars", value: "vertical" },
      { label: "Horizontal bars", value: "horizontal" },
    ],
    description: "Horizontal is best for Top-N rankings.",
  },
  {
    key: "stackMode",
    label: "Stacking",
    type: "select",
    group: "chart",
    defaultValue: "none",
    options: [
      { label: "None (grouped)", value: "none" },
      { label: "Stacked", value: "stacked" },
      { label: "100% stacked", value: "percent" },
    ],
  },
  { key: "roundedCorners", label: "Rounded corners", type: "boolean", group: "style", defaultValue: true },
  { key: "showBackground", label: "Show bar background", type: "boolean", group: "style", defaultValue: false },
  {
    key: "minPointSize",
    label: "Min bar size (px)",
    type: "number",
    group: "advanced",
    defaultValue: 0,
    min: 0,
    max: 20,
    step: 1,
    description: "Keeps tiny values visible.",
  },
];
