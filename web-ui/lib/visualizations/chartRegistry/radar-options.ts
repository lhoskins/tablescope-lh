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



export const RADAR_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show values", type: "boolean", group: "chart", defaultValue: false },
  COLOR_SCHEME_OPTION,
  {
    key: "fillOpacity",
    label: "Fill opacity",
    type: "number",
    group: "style",
    defaultValue: 0.25,
    min: 0,
    max: 1,
    step: 0.05,
  },
  { key: "domainMin", label: "Axis min", type: "number", group: "advanced", defaultValue: 0, step: 1 },
  { key: "domainMax", label: "Axis max (0 = auto)", type: "number", group: "advanced", defaultValue: 0, step: 1 },
];