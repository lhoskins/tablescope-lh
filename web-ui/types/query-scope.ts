export type QueryScope = {
  id: number;
  tenant_id: number;
  project_id: number;
  query_id: number;
  source_field: string;
  target_query_id: number;
  target_field: string;
};

export type QueryScopeFilterResponse = {
  columns: string[];
  rows: Record<string, unknown>[];
  target_query_id: number;
  target_query_name: string;
  target_field: string;
};
