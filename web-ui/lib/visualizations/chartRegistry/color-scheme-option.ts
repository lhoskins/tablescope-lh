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



export const COLOR_SCHEME_OPTION: ChartOptionDefinition = {
  key: "colorScheme",
  label: "Color scheme",
  type: "select",
  group: "style",
  defaultValue: "tablescope",
  options: [
    { label: "TableScope", value: "tablescope" },
    { label: "Ocean", value: "ocean" },
    { label: "Forest", value: "forest" },
    { label: "Warm", value: "warm" },
    { label: "Monochrome", value: "monochrome" },
  ],
};