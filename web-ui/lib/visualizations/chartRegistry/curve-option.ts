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



export const CURVE_OPTION: ChartOptionDefinition = {
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
};