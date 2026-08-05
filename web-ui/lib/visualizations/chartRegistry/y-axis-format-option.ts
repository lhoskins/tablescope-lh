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



export const Y_AXIS_FORMAT_OPTION: ChartOptionDefinition = {
  key: "yAxisFormat",
  label: "Y-axis format",
  type: "select",
  group: "advanced",
  defaultValue: "number",
  options: [
    { label: "Number", value: "number" },
    { label: "Currency", value: "currency" },
    { label: "Percent", value: "percent" },
    { label: "Compact", value: "compact" },
  ],
};