export type WidgetType = "kpi" | "line" | "bar" | "area" | "pie" | "table" | "combo";

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
