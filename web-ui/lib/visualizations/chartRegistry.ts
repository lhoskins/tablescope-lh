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

export type ChartFamily =
  | "kpi"
  | "table"
  | "line"
  | "area"
  | "bar"
  | "composed"
  | "pie";

export type ChartOptionType = "boolean" | "number" | "select";

export type ChartOptionGroup = "chart" | "style" | "advanced";

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

export interface ChartVariantDefinition {
  /** Maps to WidgetConfig.chartSubtype (empty string = default variant). */
  value: string;
  label: string;
}

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
}

const SHARED_DISPLAY_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show data labels", type: "boolean", group: "chart", defaultValue: false },
  { key: "showGrid", label: "Show grid", type: "boolean", group: "chart", defaultValue: true },
  { key: "tinyMode", label: "Tiny (sparkline) mode", type: "boolean", group: "style", defaultValue: false },
];

const LINE_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  {
    key: "lineStyle",
    label: "Line style",
    type: "select",
    group: "style",
    defaultValue: "solid",
    options: [
      { label: "Solid", value: "solid" },
      { label: "Dashed", value: "dashed" },
    ],
  },
  {
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
  },
  { key: "showDots", label: "Show points", type: "boolean", group: "style", defaultValue: false },
  { key: "connectNulls", label: "Connect nulls", type: "boolean", group: "advanced", defaultValue: false },
  { key: "dualAxis", label: "Dual Y axis", type: "boolean", group: "advanced", defaultValue: false },
];

const CURVE_OPTION: ChartOptionDefinition = {
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

const AREA_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  {
    key: "stackMode",
    label: "Stacking",
    type: "select",
    group: "chart",
    defaultValue: "none",
    options: [
      { label: "None", value: "none" },
      { label: "Stacked", value: "stacked" },
      { label: "100% stacked", value: "percent" },
    ],
  },
  CURVE_OPTION,
  { key: "showDots", label: "Show points", type: "boolean", group: "style", defaultValue: false },
  { key: "connectNulls", label: "Connect nulls", type: "boolean", group: "advanced", defaultValue: false },
  {
    key: "fillOpacity",
    label: "Fill opacity",
    type: "number",
    group: "style",
    defaultValue: 0.35,
    min: 0,
    max: 1,
    step: 0.05,
  },
];

const BAR_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  {
    key: "barLayout",
    label: "Orientation",
    type: "select",
    group: "chart",
    defaultValue: "vertical",
    options: [
      { label: "Vertical bars", value: "vertical" },
      { label: "Horizontal bars", value: "horizontal" },
    ],
    description: "Horizontal is best for Top-N rankings.",
  },
  {
    key: "stackMode",
    label: "Stacking",
    type: "select",
    group: "chart",
    defaultValue: "none",
    options: [
      { label: "None (grouped)", value: "none" },
      { label: "Stacked", value: "stacked" },
      { label: "100% stacked", value: "percent" },
    ],
  },
  { key: "roundedCorners", label: "Rounded corners", type: "boolean", group: "style", defaultValue: true },
  { key: "showBackground", label: "Show bar background", type: "boolean", group: "style", defaultValue: false },
  {
    key: "minPointSize",
    label: "Min bar size (px)",
    type: "number",
    group: "advanced",
    defaultValue: 0,
    min: 0,
    max: 20,
    step: 1,
    description: "Keeps tiny values visible.",
  },
];

const COMPOSED_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  { key: "dualAxis", label: "Dual Y axis", type: "boolean", group: "chart", defaultValue: true },
  CURVE_OPTION,
];

const PIE_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
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

export const CHART_REGISTRY: Record<WidgetType, ChartTypeDefinition> = {
  kpi: {
    type: "kpi",
    label: "KPI",
    family: "kpi",
    icon: "\u{1F522}",
    description: "A single headline metric.",
    requiredFields: ["y"],
    variants: [],
    options: [],
    bestFor: ["One important metric"],
    aiRules: ["Use KPI Card for one important metric."],
  },
  table: {
    type: "table",
    label: "Table",
    family: "table",
    icon: "\u{1F4CB}",
    description: "Raw rows in a grid.",
    requiredFields: [],
    variants: [],
    options: [],
    bestFor: ["Detail records", "Fallback for unknown chart types"],
    aiRules: ["Use a table when detail rows matter or no chart fits."],
  },
  line: {
    type: "line",
    label: "Line",
    family: "line",
    icon: "\u{1F4C8}",
    description: "Trend over a continuous or time dimension.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Straight" },
      { value: "smooth_line", label: "Smooth" },
      { value: "step_line", label: "Step" },
    ],
    options: LINE_OPTIONS,
    bestFor: ["Time trend", "SLA / cost / volume over time"],
    aiRules: [
      "Use Line for time trend.",
      "Add a reference line for a target/threshold.",
    ],
  },
  area: {
    type: "area",
    label: "Area",
    family: "area",
    icon: "\u{1F4C9}",
    description: "Cumulative or volume trend.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Area" },
      { value: "stacked_area", label: "Stacked" },
    ],
    options: AREA_OPTIONS,
    bestFor: ["Cumulative trend", "Volume over time"],
    aiRules: ["Use Area for cumulative or volume trend."],
  },
  bar: {
    type: "bar",
    label: "Bar",
    family: "bar",
    icon: "\u{1F4CA}",
    description: "Compare values across categories.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "column", label: "Column" },
      { value: "stacked_bar", label: "Stacked" },
      { value: "grouped_bar", label: "Grouped" },
      { value: "horizontal_bar", label: "Horizontal" },
      { value: "stacked_horizontal", label: "Stacked Horiz." },
    ],
    options: BAR_OPTIONS,
    bestFor: ["Category comparison", "Top-N rankings (horizontal)"],
    aiRules: [
      "Use Bar for category comparison.",
      "Use Horizontal Bar for Top-N rankings.",
      "Use Stacked Bar for category breakdown across a group.",
      "Use Grouped Bar for side-by-side comparison.",
    ],
  },
  combo: {
    type: "combo",
    label: "Combo",
    family: "composed",
    icon: "\u{1F4CA}\u{1F4C8}",
    description: "Bars plus an overlaid line, often dual-axis.",
    requiredFields: ["x", "y"],
    variants: [{ value: "bar_line", label: "Bar + Line" }],
    options: COMPOSED_OPTIONS,
    bestFor: ["Count plus rate", "Actual plus target"],
    aiRules: ["Use Combo for count plus rate, or actual plus target."],
  },
  pie: {
    type: "pie",
    label: "Pie",
    family: "pie",
    icon: "\u{1F369}",
    description: "Part-to-whole distribution.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Pie" },
      { value: "donut", label: "Donut" },
    ],
    options: PIE_OPTIONS,
    bestFor: ["Small part-to-whole distribution (<= 7 categories)"],
    aiRules: [
      "Use Donut/Pie for small part-to-whole distribution under 7 categories.",
      "Group small slices into 'Other' when there are many categories.",
    ],
  },
};

/**
 * Friendly aliases surfaced in the picker. Each maps to a renderer `type`
 * plus the variant (chartSubtype) and option overrides that realise it.
 */
export interface ChartAlias {
  alias: string;
  label: string;
  type: WidgetType;
  variant: string;
  options?: Partial<VisualizationOptions>;
}

export const CHART_ALIASES: ChartAlias[] = [
  { alias: "line", label: "Line Chart", type: "line", variant: "" },
  { alias: "area", label: "Area Chart", type: "area", variant: "" },
  { alias: "stacked_area", label: "Stacked Area", type: "area", variant: "stacked_area", options: { stackMode: "stacked" } },
  { alias: "bar", label: "Bar Chart", type: "bar", variant: "column" },
  { alias: "horizontal_bar", label: "Horizontal Bar", type: "bar", variant: "horizontal_bar" },
  { alias: "stacked_bar", label: "Stacked Bar", type: "bar", variant: "stacked_bar", options: { stackMode: "stacked" } },
  { alias: "grouped_bar", label: "Grouped Bar", type: "bar", variant: "grouped_bar" },
  { alias: "combo", label: "Combo Chart", type: "combo", variant: "bar_line", options: { dualAxis: true } },
  { alias: "pie", label: "Pie Chart", type: "pie", variant: "" },
  { alias: "donut", label: "Donut Chart", type: "pie", variant: "donut", options: { innerRadius: 55 } },
  { alias: "kpi", label: "KPI Card", type: "kpi", variant: "" },
  { alias: "table", label: "Table", type: "table", variant: "" },
];

/** Returns the registry definition for a chart type, or undefined. */
export function getChartDefinition(type: string): ChartTypeDefinition | undefined {
  return CHART_REGISTRY[type as WidgetType];
}

/** Resolves a chart type to a renderer key, falling back to "table". */
export function resolveRendererType(type: string): WidgetType {
  return CHART_REGISTRY[type as WidgetType] ? (type as WidgetType) : "table";
}

/** Builds the default options object for a chart type from the registry. */
export function getDefaultOptions(type: string): VisualizationOptions {
  const def = getChartDefinition(type);
  if (!def) return {};
  const out: Record<string, unknown> = {};
  for (const opt of def.options) {
    if (opt.defaultValue !== undefined) out[opt.key] = opt.defaultValue;
  }
  return out as VisualizationOptions;
}

/** Merges saved options over registry defaults so renderers always get a full set. */
export function withDefaults(type: string, options?: VisualizationOptions): VisualizationOptions {
  return { ...getDefaultOptions(type), ...(options ?? {}) };
}
