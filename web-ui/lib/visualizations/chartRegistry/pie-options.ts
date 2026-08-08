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



export const PIE_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  {
    key: "labelMode",
    label: "Labels",
    type: "select",
    group: "chart",
    defaultValue: "percentage",
    options: [
      { label: "None", value: "none" },
      { label: "Percentage", value: "percentage" },
      { label: "Value", value: "value" },
      { label: "Name", value: "name" },
    ],
  },
  {
    key: "innerRadius",
    label: "Donut hole %",
    type: "number",
    group: "style",
    defaultValue: 0,
    min: 0,
    max: 90,
    step: 5,
    description: "0 = full pie; raise for a donut.",
  },
  {
    key: "outerRadius",
    label: "Outer radius %",
    type: "number",
    group: "style",
    defaultValue: 80,
    min: 40,
    max: 95,
    step: 5,
  },
  {
    key: "paddingAngle",
    label: "Slice gap",
    type: "number",
    group: "style",
    defaultValue: 0,
    min: 0,
    max: 10,
    step: 1,
  },
  {
    key: "startAngle",
    label: "Start angle",
    type: "number",
    group: "advanced",
    defaultValue: 90,
    min: -360,
    max: 360,
    step: 90,
    description: "Use 180/0 for a semi-circle.",
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
  { key: "groupSmallSlices", label: "Group small slices into 'Other'", type: "boolean", group: "advanced", defaultValue: true },
  {
    key: "maxSlices",
    label: "Max slices",
    type: "number",
    group: "advanced",
    defaultValue: 7,
    min: 2,
    max: 20,
    step: 1,
  },
];