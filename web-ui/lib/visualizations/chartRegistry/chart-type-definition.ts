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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";import { ChartFamily } from "./chart-family";
import { ChartOptionDefinition } from "./chart-option-definition";
import { ChartVariantDefinition } from "./chart-variant-definition";



export interface ChartTypeDefinition {
  /** Renderer key — matches WidgetConfig.type. */
  type: WidgetType;
  label: string;
  family: ChartFamily;
  icon: string;
  description: string;
  requiredFields: Array<"x" | "y">;
  variants: ChartVariantDefinition[];
  options: ChartOptionDefinition[];
  bestFor: string[];
  aiRules: string[];
  /** Whether the planner/selector may choose this family. */
  enabled?: boolean;
}