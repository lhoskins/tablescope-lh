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
import { Y_AXIS_SCALE_OPTION } from "./y-axis-scale-option";
import { DATA_ZOOM_OPTION } from "./data-zoom-option";
import { SHARED_DISPLAY_OPTIONS } from "./shared-display-options";
import { ANALYTICAL_LAYER_OPTIONS } from "./analytical-layer-options";



export const LINE_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  Y_AXIS_SCALE_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
  ...ANALYTICAL_LAYER_OPTIONS,
  {
    key: "lineStyle",
    label: "Line style",
    type: "select",
    group: "style",
    defaultValue: "solid",
    options: [
      { label: "Solid", value: "solid" },
      { label: "Dashed", value: "dashed" },
    ],
  },
  {
    key: "curveType",
    label: "Curve",
    type: "select",
    group: "style",
    defaultValue: "monotone",
    options: [
      { label: "Straight", value: "linear" },
      { label: "Smooth", value: "monotone" },
      { label: "Step", value: "step" },
    ],
  },
  { key: "showDots", label: "Show points", type: "boolean", group: "style", defaultValue: false },
  { key: "connectNulls", label: "Connect nulls", type: "boolean", group: "advanced", defaultValue: false },
  { key: "dualAxis", label: "Dual Y axis", type: "boolean", group: "advanced", defaultValue: false },
  { key: "animate", label: "Animate", type: "boolean", group: "advanced", defaultValue: false },
];
