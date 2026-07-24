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
  | "pie"
  | "scatter"
  | "effect_scatter"
  | "radar"
  | "radial_bar"
  | "treemap"
  | "sunburst"
  | "tree"
  | "funnel"
  | "sankey"
  | "graph"
  | "parallel"
  | "lines"
  | "heatmap"
  | "candlestick"
  | "boxplot"
  | "pictorial_bar"
  | "theme_river"
  | "gauge"
  | "map";

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
  /** Option overrides applied when this variant is selected in the editor. */
  defaultOptions?: Partial<VisualizationOptions>;
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
  /** Whether the planner/selector may choose this family. */
  enabled?: boolean;
}

const SHARED_DISPLAY_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show data labels", type: "boolean", group: "chart", defaultValue: false },
  { key: "showGrid", label: "Show grid", type: "boolean", group: "chart", defaultValue: true },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  { key: "tinyMode", label: "Tiny (sparkline) mode", type: "boolean", group: "style", defaultValue: false },
];

const COLOR_SCHEME_OPTION: ChartOptionDefinition = {
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

const LEGEND_POSITION_OPTION: ChartOptionDefinition = {
  key: "legendPosition",
  label: "Legend position",
  type: "select",
  group: "chart",
  defaultValue: "bottom",
  options: [
    { label: "Top", value: "top" },
    { label: "Bottom", value: "bottom" },
    { label: "Left", value: "left" },
    { label: "Right", value: "right" },
    { label: "None", value: "none" },
  ],
};

const X_AXIS_ROTATE_OPTION: ChartOptionDefinition = {
  key: "xAxisLabelRotate",
  label: "X-axis label rotation",
  type: "number",
  group: "advanced",
  defaultValue: 0,
  min: -90,
  max: 90,
  step: 15,
};

const Y_AXIS_FORMAT_OPTION: ChartOptionDefinition = {
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

const DATA_ZOOM_OPTION: ChartOptionDefinition = {
  key: "dataZoom",
  label: "Enable zoom",
  type: "boolean",
  group: "advanced",
  defaultValue: false,
};

const ANALYTICAL_LAYER_OPTIONS: ChartOptionDefinition[] = [
  { key: "showRegressionLine", label: "Show regression line", type: "boolean", group: "advanced", defaultValue: false },
  { key: "showControlLimits", label: "Show control limits (±2σ)", type: "boolean", group: "advanced", defaultValue: false },
  { key: "showAnomalies", label: "Highlight anomalies", type: "boolean", group: "advanced", defaultValue: false },
  { key: "showChangePoint", label: "Mark largest change", type: "boolean", group: "advanced", defaultValue: false },
  { key: "confidenceBand", label: "Confidence/prediction band", type: "boolean", group: "advanced", defaultValue: false },
];

const LINE_OPTIONS: ChartOptionDefinition[] = [
  ...SHARED_DISPLAY_OPTIONS,
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
  ...ANALYTICAL_LAYER_OPTIONS,
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
  { key: "animate", label: "Animate", type: "boolean", group: "advanced", defaultValue: false },
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
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
  { key: "showRegressionLine", label: "Show regression line", type: "boolean", group: "advanced", defaultValue: false },
  { key: "showControlLimits", label: "Show control limits (±2σ)", type: "boolean", group: "advanced", defaultValue: false },
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
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
  { key: "showControlLimits", label: "Show control limits (±2σ)", type: "boolean", group: "advanced", defaultValue: false },
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
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
  { key: "dualAxis", label: "Dual Y axis", type: "boolean", group: "chart", defaultValue: true },
  CURVE_OPTION,
  { key: "showRegressionLine", label: "Show regression line", type: "boolean", group: "advanced", defaultValue: false },
  { key: "showControlLimits", label: "Show control limits (±2σ)", type: "boolean", group: "advanced", defaultValue: false },
];

const PIE_OPTIONS: ChartOptionDefinition[] = [
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

const SCATTER_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showGrid", label: "Show grid", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show point labels", type: "boolean", group: "chart", defaultValue: false },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  DATA_ZOOM_OPTION,
  { key: "bubble", label: "Bubble (size by Z)", type: "boolean", group: "chart", defaultValue: false, description: "Sizes each point by the Z column." },
  { key: "showTrendLine", label: "Line of best fit", type: "boolean", group: "advanced", defaultValue: false },
];

const HEATMAP_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show cell values", type: "boolean", group: "chart", defaultValue: false },
  COLOR_SCHEME_OPTION,
  { key: "showRegressionLine", label: "Show regression line", type: "boolean", group: "advanced", defaultValue: false },
  { key: "showControlLimits", label: "Show control limits (±2σ)", type: "boolean", group: "advanced", defaultValue: false },
];

const RADAR_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLabels", label: "Show values", type: "boolean", group: "chart", defaultValue: false },
  COLOR_SCHEME_OPTION,
  {
    key: "fillOpacity",
    label: "Fill opacity",
    type: "number",
    group: "style",
    defaultValue: 0.25,
    min: 0,
    max: 1,
    step: 0.05,
  },
  { key: "domainMin", label: "Axis min", type: "number", group: "advanced", defaultValue: 0, step: 1 },
  { key: "domainMax", label: "Axis max (0 = auto)", type: "number", group: "advanced", defaultValue: 0, step: 1 },
];

const RADIAL_BAR_OPTIONS: ChartOptionDefinition[] = [
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

const TREEMAP_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLabels", label: "Show labels", type: "boolean", group: "chart", defaultValue: true },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const FUNNEL_OPTIONS: ChartOptionDefinition[] = [
  { key: "showLabels", label: "Show labels", type: "boolean", group: "chart", defaultValue: true },
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  { key: "showLegend", label: "Show legend", type: "boolean", group: "chart", defaultValue: false },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
];

const SANKEY_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  { key: "nodePadding", label: "Node padding", type: "number", group: "style", defaultValue: 20, min: 0, max: 60, step: 2 },
  { key: "nodeWidth", label: "Node width", type: "number", group: "style", defaultValue: 12, min: 4, max: 40, step: 2 },
];

const SUNBURST_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const TREE_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const GRAPH_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  { key: "showLabels", label: "Show labels", type: "boolean", group: "chart", defaultValue: true },
];

const PARALLEL_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const LINES_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const CANDLESTICK_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const BOXPLOT_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

const PICTORIAL_BAR_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
  Y_AXIS_FORMAT_OPTION,
  X_AXIS_ROTATE_OPTION,
  DATA_ZOOM_OPTION,
];

const THEME_RIVER_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
  LEGEND_POSITION_OPTION,
];

const MAP_OPTIONS: ChartOptionDefinition[] = [
  { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
  COLOR_SCHEME_OPTION,
];

export const CHART_REGISTRY: Partial<Record<WidgetType, ChartTypeDefinition>> = {
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
      { value: "", label: "Straight", defaultOptions: { curveType: "linear", lineStyle: "solid", dualAxis: false, tinyMode: false } },
      { value: "smooth_line", label: "Smooth", defaultOptions: { curveType: "monotone" } },
      { value: "step_line", label: "Step", defaultOptions: { curveType: "step" } },
      { value: "dashed_line", label: "Dashed", defaultOptions: { lineStyle: "dashed" } },
      { value: "biaxial_line", label: "Biaxial", defaultOptions: { dualAxis: true } },
      { value: "animated_line", label: "Animated", defaultOptions: { animate: true } },
      { value: "tiny_line", label: "Tiny", defaultOptions: { tinyMode: true } },
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
      { value: "", label: "Area", defaultOptions: { stackMode: "none" } },
      { value: "stacked_area", label: "Stacked", defaultOptions: { stackMode: "stacked" } },
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
      { value: "column", label: "Column", defaultOptions: { barLayout: "vertical", stackMode: "none" } },
      { value: "stacked_bar", label: "Stacked", defaultOptions: { barLayout: "vertical", stackMode: "stacked" } },
      { value: "grouped_bar", label: "Grouped", defaultOptions: { barLayout: "vertical", stackMode: "none" } },
      { value: "horizontal_bar", label: "Horizontal", defaultOptions: { barLayout: "horizontal", stackMode: "none" } },
      { value: "stacked_horizontal", label: "Stacked Horiz.", defaultOptions: { barLayout: "horizontal", stackMode: "stacked" } },
      { value: "positive_negative", label: "Pos / Neg", defaultOptions: { barLayout: "vertical", colorBySign: true } },
      { value: "waterfall", label: "Waterfall", defaultOptions: { barLayout: "vertical", cumulative: true } },
      { value: "population_pyramid", label: "Pyramid", defaultOptions: { barLayout: "horizontal" } },
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
    variants: [
      { value: "bar_line", label: "Bar + Line", defaultOptions: { dualAxis: true } },
      { value: "dual_line", label: "Dual Line", defaultOptions: { dualAxis: true } },
    ],
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
      { value: "", label: "Pie", defaultOptions: { innerRadius: 0, startAngle: 90, endAngle: -270 } },
      { value: "donut", label: "Donut", defaultOptions: { innerRadius: 55, startAngle: 90, endAngle: -270 } },
      { value: "two_level", label: "Two-level", defaultOptions: { innerRadius: 45 } },
      { value: "gauge", label: "Gauge", defaultOptions: { innerRadius: 55, startAngle: 180, endAngle: 0, groupSmallSlices: false } },
    ],
    options: PIE_OPTIONS,
    bestFor: ["Small part-to-whole distribution (<= 7 categories)"],
    aiRules: [
      "Use Donut/Pie for small part-to-whole distribution under 7 categories.",
      "Group small slices into 'Other' when there are many categories.",
    ],
  },
  scatter: {
    type: "scatter",
    label: "Scatter / Bubble",
    family: "scatter",
    icon: "\u{1F4A0}",
    description: "Correlation between two numeric measures; bubble adds a third.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Scatter", defaultOptions: { bubble: false, showTrendLine: false } },
      { value: "bubble", label: "Bubble", defaultOptions: { bubble: true } },
      { value: "best_fit", label: "Best fit", defaultOptions: { showTrendLine: true } },
    ],
    options: SCATTER_OPTIONS,
    bestFor: ["Cost vs utilization", "Age vs risk", "Correlation analysis"],
    aiRules: ["Use Scatter/Bubble for correlation between numeric measures."],
  },
  radar: {
    type: "radar",
    label: "Radar",
    family: "radar",
    icon: "\u{1F578}\u{FE0F}",
    description: "Compare multiple dimensions for one or more entities.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Radar" },
      { value: "scorecard", label: "Scorecard" },
    ],
    options: RADAR_OPTIONS,
    bestFor: ["Supplier scorecard", "Service health", "Maturity comparison"],
    aiRules: ["Use Radar when comparing multiple dimensions for one or more entities."],
  },
  radial_bar: {
    type: "radial_bar",
    label: "Radial Bar",
    family: "radial_bar",
    icon: "\u{1F3AF}",
    description: "Percentage-to-target metrics drawn as concentric arcs.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Radial Bar" },
      { value: "multi_ring", label: "Multi-ring" },
    ],
    options: RADIAL_BAR_OPTIONS,
    bestFor: ["Patch / SLA compliance", "Budget utilization", "OEE"],
    aiRules: ["Use Radial Bar for percentage-to-target metrics."],
  },
  treemap: {
    type: "treemap",
    label: "Treemap",
    family: "treemap",
    icon: "\u{1F9E9}",
    description: "Hierarchical part-to-whole by rectangle area.",
    requiredFields: ["x", "y"],
    variants: [
      { value: "", label: "Treemap" },
      { value: "nested", label: "Nested" },
    ],
    options: TREEMAP_OPTIONS,
    bestFor: ["Cloud cost by service", "Spend by category", "Revenue by region"],
    aiRules: ["Use Treemap for hierarchical spend/value."],
  },
  funnel: {
    type: "funnel",
    label: "Funnel",
    family: "funnel",
    icon: "\u{1FA9D}",
    description: "Stage-by-stage progression of a count.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Funnel" }],
    options: FUNNEL_OPTIONS,
    bestFor: ["Ticket lifecycle", "Approval stages", "Pipeline"],
    aiRules: ["Use Funnel for stage progression."],
  },
  sankey: {
    type: "sankey",
    label: "Sankey",
    family: "sankey",
    icon: "\u{1F500}",
    description: "Flow from source to target categories, weighted by value.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Sankey" }],
    options: SANKEY_OPTIONS,
    bestFor: ["Source \u2192 service \u2192 group flows", "Provider \u2192 BU spend"],
    aiRules: ["Use Sankey for source-to-target flows."],
  },
  heatmap: {
    type: "heatmap",
    label: "Heatmap",
    family: "heatmap",
    icon: "\u{1F525}",
    description: "Density of a value across two categorical dimensions.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Heatmap" }],
    options: HEATMAP_OPTIONS,
    bestFor: ["Two-dimension breakdown", "Correlation matrix", "Volume by region and period"],
    aiRules: ["Use Heatmap when a value varies across two categorical dimensions."],
    enabled: true,
  },
  effect_scatter: {
    type: "effect_scatter",
    label: "Effect Scatter",
    family: "effect_scatter",
    icon: "\u{2728}",
    description: "Scatter with animated emphasis on each point.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Effect Scatter" }],
    options: SCATTER_OPTIONS,
    bestFor: ["Anomalies", "Highlights", "Time-point events"],
    aiRules: ["Use Effect Scatter to emphasize individual points."],
    enabled: true,
  },
  gauge: {
    type: "gauge",
    label: "Gauge",
    family: "gauge",
    icon: "\u{1F6E0}\u{FE0F}",
    description: "A single value shown as a radial gauge.",
    requiredFields: ["y"],
    variants: [
      { value: "", label: "Gauge" },
      { value: "semi", label: "Semi-circle" },
    ],
    options: [
      { key: "showTooltip", label: "Show tooltip", type: "boolean", group: "chart", defaultValue: true },
      { key: "domainMin", label: "Min value", type: "number", group: "advanced", defaultValue: 0, step: 1 },
      { key: "domainMax", label: "Max value", type: "number", group: "advanced", defaultValue: 100, step: 1 },
      { key: "innerRadius", label: "Inner radius %", type: "number", group: "style", defaultValue: 55, min: 0, max: 90, step: 5 },
      { key: "outerRadius", label: "Outer radius %", type: "number", group: "style", defaultValue: 80, min: 40, max: 100, step: 5 },
      COLOR_SCHEME_OPTION,
    ],
    bestFor: ["Current value vs target", "SLA", "Utilization"],
    aiRules: ["Use Gauge for a single current value against a known scale."],
    enabled: true,
  },
  sunburst: {
    type: "sunburst",
    label: "Sunburst",
    family: "sunburst",
    icon: "\u{1F31F}",
    description: "A radial hierarchical part-to-whole chart.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Sunburst" }],
    options: SUNBURST_OPTIONS,
    bestFor: ["Hierarchical part-to-whole", "Nested categories"],
    aiRules: ["Use Sunburst for nested hierarchical breakdowns."],
    enabled: true,
  },
  tree: {
    type: "tree",
    label: "Tree",
    family: "tree",
    icon: "\u{1F334}",
    description: "Branching hierarchy from a root node.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Tree" }],
    options: TREE_OPTIONS,
    bestFor: ["Org chart", "Nested categories", "Decision trees"],
    aiRules: ["Use Tree for branching hierarchical data."],
    enabled: true,
  },
  graph: {
    type: "graph",
    label: "Graph",
    family: "graph",
    icon: "\u{1F4DA}",
    description: "Nodes and edges showing relationships.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Graph" }],
    options: GRAPH_OPTIONS,
    bestFor: ["Network relationships", "Dependency maps"],
    aiRules: ["Use Graph when nodes are connected by a value."],
    enabled: true,
  },
  parallel: {
    type: "parallel",
    label: "Parallel Coordinates",
    family: "parallel",
    icon: "\u{1F4C9}",
    description: "Compare many numeric dimensions at once.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Parallel" }],
    options: PARALLEL_OPTIONS,
    bestFor: ["Multi-dimensional comparison", "Feature profiles"],
    aiRules: ["Use Parallel Coordinates for comparing many numeric dimensions."],
    enabled: true,
  },
  lines: {
    type: "lines",
    label: "Lines",
    family: "lines",
    icon: "\u{1F4E5}",
    description: "Connected line paths, useful for movement or flows.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Lines" }],
    options: LINES_OPTIONS,
    bestFor: ["Movement paths", "Origin-destination flows"],
    aiRules: ["Use Lines for origin-destination or movement paths."],
    enabled: true,
  },
  candlestick: {
    type: "candlestick",
    label: "Candlestick",
    family: "candlestick",
    icon: "\u{1F4C8}",
    description: "Open/high/low/close price data.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Candlestick" }],
    options: CANDLESTICK_OPTIONS,
    bestFor: ["OHLC price data", "Financial series"],
    aiRules: ["Use Candlestick for open/high/low/close data."],
    enabled: true,
  },
  boxplot: {
    type: "boxplot",
    label: "Boxplot",
    family: "boxplot",
    icon: "\u{1F4CA}",
    description: "Distribution summary with quartiles and outliers.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Boxplot" }],
    options: BOXPLOT_OPTIONS,
    bestFor: ["Distribution comparison", "Statistical summaries"],
    aiRules: ["Use Boxplot to compare distributions across categories."],
    enabled: true,
  },
  pictorial_bar: {
    type: "pictorial_bar",
    label: "Pictorial Bar",
    family: "pictorial_bar",
    icon: "\u{1F4A0}",
    description: "Bars rendered as symbols or icons.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Pictorial Bar" }],
    options: PICTORIAL_BAR_OPTIONS,
    bestFor: ["Ikonographic comparisons", "Category ranking"],
    aiRules: ["Use Pictorial Bar for category comparisons with icons."],
    enabled: true,
  },
  theme_river: {
    type: "theme_river",
    label: "Theme River",
    family: "theme_river",
    icon: "\u{1F3DE}\u{FE0F}",
    description: "Event or value streams over time.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Theme River" }],
    options: THEME_RIVER_OPTIONS,
    bestFor: ["Event streams", "Temporal themes"],
    aiRules: ["Use Theme River for value streams over a continuous axis."],
    enabled: true,
  },
  map: {
    type: "map",
    label: "Map",
    family: "map",
    icon: "\u{1F5FA}\u{FE0F}",
    description: "Geographic values by region.",
    requiredFields: ["x", "y"],
    variants: [{ value: "", label: "Map" }],
    options: MAP_OPTIONS,
    bestFor: ["Geographic distribution", "Regional metrics"],
    aiRules: ["Use Map for geographic region values."],
    enabled: true,
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
  { alias: "scatter", label: "Scatter Chart", type: "scatter", variant: "" },
  { alias: "bubble", label: "Bubble Chart", type: "scatter", variant: "bubble", options: { bubble: true } },
  { alias: "radar", label: "Radar Chart", type: "radar", variant: "" },
  { alias: "radial_bar", label: "Radial Bar", type: "radial_bar", variant: "" },
  { alias: "treemap", label: "Treemap", type: "treemap", variant: "" },
  { alias: "funnel", label: "Funnel", type: "funnel", variant: "" },
  { alias: "sankey", label: "Sankey", type: "sankey", variant: "" },
  { alias: "heatmap", label: "Heatmap", type: "heatmap", variant: "" },
  { alias: "effect_scatter", label: "Effect Scatter", type: "effect_scatter", variant: "" },
  { alias: "gauge", label: "Gauge", type: "gauge", variant: "" },
  { alias: "sunburst", label: "Sunburst", type: "sunburst", variant: "" },
  { alias: "tree", label: "Tree", type: "tree", variant: "" },
  { alias: "graph", label: "Graph", type: "graph", variant: "" },
  { alias: "parallel", label: "Parallel Coordinates", type: "parallel", variant: "" },
  { alias: "lines", label: "Lines", type: "lines", variant: "" },
  { alias: "candlestick", label: "Candlestick", type: "candlestick", variant: "" },
  { alias: "boxplot", label: "Boxplot", type: "boxplot", variant: "" },
  { alias: "pictorial_bar", label: "Pictorial Bar", type: "pictorial_bar", variant: "" },
  { alias: "theme_river", label: "Theme River", type: "theme_river", variant: "" },
  { alias: "map", label: "Map", type: "map", variant: "" },
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
