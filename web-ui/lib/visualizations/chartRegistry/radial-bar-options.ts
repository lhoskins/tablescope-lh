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



export const RADIAL_BAR_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show values", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  {
    key: "innerRadius",
    label: "Inner radius %",
    type: "number",
    group: "style",
    defaultValue: 30,
    min: 0,
    max: 90,
    step: 5,
  },
  {
    key: "outerRadius",
    label: "Outer radius %",
    type: "number",
    group: "style",
    defaultValue: 90,
    min: 40,
    max: 100,
    step: 5,
  },
  { key: "domainMax", label: "Max value (0 = auto)", type: "number", group: "advanced", defaultValue: 100, step: 1, description: "Use 100 for percentage-to-target metrics." },
  {
    key: "startAngle",
    label: "Start angle",
    type: "number",
    group: "advanced",
    defaultValue: 90,
    min: -360,
    max: 360,
    step: 90,
  },
  {
    key: "endAngle",
    label: "End angle",
    type: "number",
    group: "advanced",
    defaultValue: -270,
    min: -360,
    max: 360,
    step: 90,
  },
];