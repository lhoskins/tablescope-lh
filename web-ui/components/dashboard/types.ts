export type WidgetType = "kpi" | "line" | "bar" | "area" | "pie" | "table";

export type WidgetDataSource = {
  kind: "query" | "datasource" | "custom_sql";
  queryId?: number;
  viewName?: string;
  customSql?: string;
};

export type WidgetConfig = {
  id: string;
  type: WidgetType;
  title: string;
  dataSource: WidgetDataSource;
  xKey: string;
  yKey: string;
  aggregation?: string;
  colSpan: number;
  position: number;
};

export type DashboardConfig = {
  widgets: WidgetConfig[];
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
