"use client";

import { apiClient } from "@/lib/api-client";

export interface ConnectedSource {
  id: string;
  kind: "database" | "saas" | "network_repository";
  source?: "owned" | "assigned" | "shared";
  friendlyName: string;
  connectorType: string;
  displayLocation: string;
  status: string;
  enabled: boolean;
  allowedActions: string[];
  connectionId?: number;
  credentialId?: number;
  dataSourceId?: number;
  databaseName?: string;
  port?: number;
  assignedBy?: string | null;
  readOnly?: boolean;
}

export interface AllDataSource {
  id: string;
  backendId: number;
  kind: string;
  name: string;
  viewName: string;
  sourceType: string;
  connectorType: string | null;
  dbType: string | null;
  schemaName?: string | null;
  tableName?: string | null;
  columns: number;
  projectId: number | null;
  projectName: string | null;
  ownerId: number | null;
  ownerName: string | null;
  createdAt: string | null;
}

export interface AllDataSourcesResponse {
  items: AllDataSource[];
  total: number;
  next_cursor: string | null;
}

export interface AllDataSourcesFilters {
  project_id?: number;
  search?: string;
  source_type?: string;
  assignment?: "all" | "assigned" | "unassigned";
  owner_id?: number;
  created_after?: string;
  cursor?: string;
  limit?: number;
}

export interface ValidateSelectionRequest {
  project_id: number;
  source_ids: string[];
}

export interface ValidateSelectionResponse {
  valid: string[];
  invalid: Record<string, string>;
}

export function listConnectedSources(): Promise<ConnectedSource[]> {
  return apiClient.get<{ items: ConnectedSource[] }>("/api/connected-sources").then((r) => r.items);
}

export async function listAllDataSources(
  filters: AllDataSourcesFilters = {},
): Promise<AllDataSourcesResponse> {
  const params = new URLSearchParams();
  if (filters.project_id !== undefined) params.set("project_id", String(filters.project_id));
  if (filters.search) params.set("search", filters.search);
  if (filters.source_type) params.set("source_type", filters.source_type);
  if (filters.assignment) params.set("assignment", filters.assignment);
  if (filters.owner_id !== undefined) params.set("owner_id", String(filters.owner_id));
  if (filters.created_after) params.set("created_after", filters.created_after);
  if (filters.cursor) params.set("cursor", filters.cursor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  return apiClient.get<AllDataSourcesResponse>(
    `/api/projects/datasources/all?${params.toString()}`,
  );
}

export function validateDataSourceSelection(
  body: ValidateSelectionRequest,
): Promise<ValidateSelectionResponse> {
  return apiClient.post<ValidateSelectionResponse>("/api/projects/datasources/validate", body);
}
