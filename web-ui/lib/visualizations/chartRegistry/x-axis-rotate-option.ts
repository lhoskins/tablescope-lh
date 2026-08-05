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



export const X_AXIS_ROTATE_OPTION: ChartOptionDefinition = {
  key: "xAxisLabelRotate",
  label: "X-axis label rotation",
  type: "number",
  group: "advanced",
  defaultValue: 0,
  min: -90,
  max: 90,
  step: 15,
};