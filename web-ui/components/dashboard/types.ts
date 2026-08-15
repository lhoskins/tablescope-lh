export type WidgetType =
  | "kpi"
  | "line"
  | "bar"
  | "area"
  | "pie"
  | "table"
  | "combo"
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

/**
 * Reference line drawn on a cartesian chart (line/area/bar/combo).
 */
export type ReferenceLineConfig = {
  axis?: "x" | "y";
  value: number;
  label?: string;
};

/**
 * Option-driven visualization settings layered on top of the base
 * chart `type` + `chartSubtype`. Every field is optional; renderers fall
 * back to defaults that preserve the previous (pre-options) appearance,
 * which keeps existing saved dashboards working unchanged.
 */
export type VisualizationOptions = {
  // Shared
  showLegend?: boolean;
  showLabels?: boolean;
  showGrid?: boolean;
  tinyMode?: boolean;
  colorScheme?: "tablescope" | "ocean" | "forest" | "warm" | "monochrome";
  legendPosition?: "top" | "bottom" | "left" | "right" | "none";
  showTooltip?: boolean;
  // Axis & formatting
  xAxisLabelRotate?: number;
  yAxisFormat?: "number" | "currency" | "percent" | "compact";
  dataZoom?: boolean;
  // Line / Area
  lineStyle?: "solid" | "dashed";
  curveType?: "linear" | "monotone" | "step";
  connectNulls?: boolean;
  showDots?: boolean;
  referenceLines?: ReferenceLineConfig[];
  // Line / Composed dual axis: series names rendered on the right axis
  dualAxis?: boolean;
  rightAxisSeries?: string[];
  // Area / Bar stacking
  stackMode?: "none" | "stacked" | "percent";
  fillOpacity?: number;
  // Bar
  roundedCorners?: boolean;
  barLayout?: "vertical" | "horizontal";
  showBackground?: boolean;
  minPointSize?: number;
  // Pie / Donut
  innerRadius?: number;
  outerRadius?: number;
  startAngle?: number;
  endAngle?: number;
  paddingAngle?: number;
  labelMode?: "none" | "percentage" | "value" | "name";
  maxSlices?: number;
  groupSmallSlices?: boolean;
  // Scatter / Bubble
  bubble?: boolean;
  zColumn?: string;
  showTrendLine?: boolean;
  // Animation (animated time series, etc.)
  animate?: boolean;
  // Pie two-level (inner ring grouped by a second column)
  innerGroupColumn?: string;
  // Bar coloring / cumulative behaviours
  colorBySign?: boolean;
  cumulative?: boolean;
  // Percent-change time series
  signedPercentAxis?: boolean;
  percentChangeTooltip?: boolean;
  comparisonLabel?: string;
  // Radar / Radial bar
  domainMin?: number;
  domainMax?: number;
  // Analytical layers
  showRegressionLine?: boolean;
  showControlLimits?: boolean;
  showAnomalies?: boolean;
  showChangePoint?: boolean;
  confidenceBand?: boolean;
  /**
   * Explicit 0-based point positions to mark, supplied by whatever analysed the
   * data. When present these win over `showAnomalies`, which re-derives outliers
   * with a 2-sigma rule and would otherwise mark different points than the
   * method reported.
   */
  markedIndices?: number[];
  /** Explicit change-point position; wins over `showChangePoint`'s largest-jump guess. */
  markedChangePointIndex?: number;
  // Treemap / Funnel
  // Sankey
  sourceColumn?: string;
  targetColumn?: string;
  nodePadding?: number;
  nodeWidth?: number;
};

export type ChartSubtype =
  // Bar variants
  | "column"           // vertical bars (default bar)
  | "stacked_bar"      // stacked vertical bars
  | "grouped_bar"      // side-by-side bars (grouped)
  | "horizontal_bar"   // horizontal bars
  | "stacked_horizontal"
  | "positive_negative" // color bars by sign
  | "waterfall"         // running cumulative total
  | "population_pyramid" // mirrored horizontal bars
  // Line variants
  | "smooth_line"      // curved/spline
  | "step_line"        // step function
  | "dashed_line"
  | "biaxial_line"
  | "tiny_line"
  | "animated_line"
  // Area variants
  | "stacked_area"
  // Pie variants
  | "donut"
  | "two_level"        // inner ring grouped by a second column
  | "gauge"            // semi-circle gauge
  // Combo
  | "bar_line"         // bars + overlay line
  | "dual_line"        // two line series, often dual-axis
  // Scatter variants
  | "bubble"
  | "best_fit"         // scatter + linear trend line
  // Radar variants
  | "scorecard"
  // Radial bar variants
  | "multi_ring"
  // Treemap variants
  | "nested"
  // Gauge variants
  | "semi";

export type WidgetDataSource = {
  kind: "query" | "datasource" | "custom_sql";
  queryId?: number;
  viewName?: string;
  customSql?: string;
};

export type WidgetFilter = {
  column: string;
  operator: string; // eq, neq, gt, lt, gte, lte, between, in, not_in, contains
  value: string | number | string[];
  value2?: number; // for "between"
};

/**
 * Click-interaction configuration for a widget. Stored in widget JSON so no
 * migration is required. `sourceField` defaults to the widget's xColumn when
 * unset. `scopeId` references an existing query_scope used for drilldown.
 */
export type WidgetClickAction =
  | "none"
  | "cross_filter"
  | "drilldown"
  | "drilldown_and_filter";

export type WidgetInteractions = {
  enabled?: boolean;
  clickAction?: WidgetClickAction;
  sourceField?: string;
  scopeId?: number;
  applyTo?: "dashboard";
};

/** Maps a widget to the date column the dashboard date-range filter applies to. */
export type WidgetDateField = {
  enabled?: boolean;
  field?: string;
};

export type WidgetConfig = {
  id: string;
  type: WidgetType;
  chartSubtype?: ChartSubtype;
  title: string;
  dataSource: WidgetDataSource;
  // Axis & Aggregation
  xColumn: string;
  xColumnType?: "date" | "string" | "number";
  dateGranularity?: "day" | "week" | "month" | "quarter" | "year";
  yColumn: string;
  aggregation: "sum" | "avg" | "count" | "min" | "max";
  // Secondary Y (for combo charts)
  y2Column?: string;
  y2Aggregation?: "sum" | "avg" | "count" | "min" | "max";
  // Grouping
  groupByColumn?: string;
  // Sort & Limit
  sortBy: "x_asc" | "x_desc" | "y_asc" | "y_desc";
  limit?: number;
  // Filters
  filters: WidgetFilter[];
  // Option-driven visualization settings (registry-backed)
  visualizationOptions?: VisualizationOptions;
  // Click interaction config (drilldown / cross-filter)
  interactions?: WidgetInteractions;
  // Date field mapping for the dashboard date-range filter
  dateField?: WidgetDateField;
  // Layout (grid-based)
  colSpan: number;
  rowSpan?: number;
  position: number;
  // Grid layout (react-grid-layout)
  gridX?: number;
  gridY?: number;
  gridW?: number;
  gridH?: number;
  // Legacy compat (deprecated — use xColumn/yColumn)
  xKey?: string;
  yKey?: string;
};

export type DashboardFilter = {
  id: string;
  column: string;
  columnType: "date" | "string" | "number";
  filterType: "date_range" | "multi_select" | "numeric_range" | "text";
  value: unknown;
};

export type DashboardConfig = {
  widgets: WidgetConfig[];
  globalFilters?: DashboardFilter[];
  /** Shared visual language used by template-created dashboards. */
  presentation?: "operational_insight";
  /** Template collection, group, icon and parameter bindings. */
  dashboardTemplate?: Record<string, unknown>;
  /** Reusable AI-managed narrative widgets rendered above the chart grid. */
  operationalWidgets?: Array<Record<string, unknown>>;
};

export type Dashboard = {
  id: number;
  project_id: number;
  owner_id: number | null;
  tenant_id: number;
  name: string;
  description: string | null;
  status: string;
  config: DashboardConfig;
  created_at: string;
  updated_at: string;
};

export type ColumnInfo = {
  name: string;
  type: "date" | "string" | "number" | "boolean";
};

// ── Dashboard runtime interactivity (ephemeral, not persisted) ────────

/** A normalized click event emitted by a chart element. */
export type ChartClickEvent = {
  sourceField: string;
  value: string | number;
  label: string;
};

/** A cross-filter created by clicking a chart in cross-filter mode. */
export type CrossFilter = {
  id: string;
  sourceWidgetId: string;
  sourceField: string;
  value: string | number;
  label: string;
};

/** The active dashboard-level date range. */
export type DashboardDateRange = {
  preset: string; // e.g. "last_30_days", "custom"
  start: string; // ISO date (yyyy-mm-dd)
  end: string; // ISO date (yyyy-mm-dd)
};

/** Ephemeral dashboard interaction state (date range + cross-filters). */
export type DashboardRuntimeState = {
  dateRange: DashboardDateRange | null;
  crossFilters: CrossFilter[];
};
