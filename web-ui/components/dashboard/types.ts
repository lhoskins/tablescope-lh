export type WidgetType = "kpi" | "line" | "bar" | "area" | "pie" | "table" | "combo";

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
};

export type ChartSubtype =
  // Bar variants
  | "column"           // vertical bars (default bar)
  | "stacked_bar"      // stacked vertical bars
  | "grouped_bar"      // side-by-side bars (grouped)
  | "horizontal_bar"   // horizontal bars
  | "stacked_horizontal"
  // Line variants
  | "smooth_line"      // curved/spline
  | "step_line"        // step function
  // Area variants
  | "stacked_area"
  // Pie variants
  | "donut"
  // Combo
  | "bar_line";        // bars + overlay line

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
