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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { ChartOptionType } from "./chart-option-type";
import { ChartOptionGroup } from "./chart-option-group";



export interface ChartOptionDefinition {
  /** Key into VisualizationOptions. */
  key: keyof VisualizationOptions;
  label: string;
  type: ChartOptionType;
  group: ChartOptionGroup;
  defaultValue?: unknown;
  /** For `select` options. */
  options?: Array<{ label: string; value: string | number | boolean }>;
  /** Min/max for `number` options. */
  min?: number;
  max?: number;
  step?: number;
  description?: string;
}