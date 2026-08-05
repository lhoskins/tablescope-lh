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

import type { WidgetType, VisualizationOptions } from "@/components/dashboard/types";


export interface ChartVariantDefinition {
  /** Maps to WidgetConfig.chartSubtype (empty string = default variant). */
  value: string;
  label: string;
  /** Option overrides applied when this variant is selected in the editor. */
  defaultOptions?: Partial<VisualizationOptions>;
}