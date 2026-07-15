import { apiClient } from "@/lib/api-client";

export interface RepositoryConnection {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  connector_type: string;
  status: string;
  config: Record<string, unknown>;
  has_credential: boolean;
  project_id: number | null;
  is_enabled: boolean;
  scan_schedule: string | null;
  last_scan_id: number | null;
  last_successful_scan_at: string | null;
  version: number;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryConnectionCreate {
  name: string;
  description?: string;
  connector_type?: string;
  config: Record<string, unknown>;
  secret?: Record<string, unknown>;
  project_id?: number;
  is_enabled?: boolean;
  scan_schedule?: string;
}

export interface RepositoryConnectionUpdate {
  name?: string;
  description?: string;
  config?: Record<string, unknown>;
  secret?: Record<string, unknown>;
  project_id?: number;
  is_enabled?: boolean;
  scan_schedule?: string;
  expected_version: number;
}

export interface ConnectionCheck {
  name: string;
  status: "passed" | "failed" | "skipped";
  message?: string | null;
}

export interface ConnectionTestResult {
  success: boolean;
  checks: ConnectionCheck[];
  sample?: Record<string, unknown> | null;
  warnings: string[];
  tested_at: string;
}

export interface RepositoryScan {
  id: number;
  connection_id: number;
  tenant_id: number;
  trigger_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  heartbeat_at: string | null;
  files_seen: number;
  directories_seen: number;
  bytes_seen: number;
  added_count: number;
  changed_count: number;
  deleted_count: number;
  skipped_count: number;
  error_count: number;
  error_code: string | null;
  error_message: string | null;
  worker_id: string | null;
  retry_attempt: number;
  job_id?: string;
}

export interface RepositoryProfileResponse {
  id: number;
  tenant_id: number;
  connection_id: number;
  scan_id: number | null;
  profile: Record<string, unknown>;
  is_current: boolean;
  created_at: string;
  updated_at: string;
}

export interface RepositoryItem {
  id: number;
  tenant_id: number;
  connection_id: number;
  external_id: string;
  relative_path: string;
  name: string;
  parent_path: string;
  item_type: string;
  extension: string | null;
  mime_type: string | null;
  size: number | null;
  source_created_at: string | null;
  source_modified_at: string | null;
  etag: string | null;
  content_hash: string | null;
  metadata: Record<string, unknown>;
  is_deleted: boolean;
  deleted_at: string | null;
  first_seen_scan_id: number | null;
  last_seen_scan_id: number | null;
  last_changed_scan_id: number | null;
  extraction_status: string;
  created_at: string;
  updated_at: string;
}

export interface RepositoryItemsResponse {
  items: RepositoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface RepositoryConnectorType {
  connector_type: string;
  name: string;
}

export function listRepositoryConnectorTypes(): Promise<
  RepositoryConnectorType[]
> {
  return apiClient.get<RepositoryConnectorType[]>(
    "/api/repository-connectors/types",
  );
}

export function listRepositoryConnections(): Promise<RepositoryConnection[]> {
  return apiClient.get<RepositoryConnection[]>("/api/repository-connectors");
}

export function createRepositoryConnection(
  body: RepositoryConnectionCreate,
): Promise<RepositoryConnection> {
  return apiClient.post<RepositoryConnection>(
    "/api/repository-connectors",
    body,
  );
}

export function updateRepositoryConnection(
  id: number,
  body: RepositoryConnectionUpdate,
): Promise<RepositoryConnection> {
  return apiClient.patch<RepositoryConnection>(
    `/api/repository-connectors/${id}`,
    body,
  );
}

export function deleteRepositoryConnection(
  id: number,
): Promise<RepositoryConnection> {
  return apiClient.delete<RepositoryConnection>(
    `/api/repository-connectors/${id}`,
  );
}

export function testRepositoryConnectionConfig(
  body: RepositoryConnectionCreate,
): Promise<ConnectionTestResult> {
  return apiClient.post<ConnectionTestResult>(
    "/api/repository-connectors/test",
    body,
  );
}

export function testExistingRepositoryConnection(
  id: number,
): Promise<ConnectionTestResult> {
  return apiClient.post<ConnectionTestResult>(
    `/api/repository-connectors/${id}/test`,
    {},
  );
}

export function startRepositoryScan(id: number): Promise<RepositoryScan> {
  return apiClient.post<RepositoryScan>(
    `/api/repository-connectors/${id}/scans`,
    {},
  );
}

export function listRepositoryScans(id: number): Promise<RepositoryScan[]> {
  return apiClient.get<RepositoryScan[]>(
    `/api/repository-connectors/${id}/scans`,
  );
}

export function getRepositoryScan(
  connectionId: number,
  scanId: number,
): Promise<RepositoryScan> {
  return apiClient.get<RepositoryScan>(
    `/api/repository-connectors/${connectionId}/scans/${scanId}`,
  );
}

export function getRepositoryProfile(
  id: number,
): Promise<RepositoryProfileResponse> {
  return apiClient.get<RepositoryProfileResponse>(
    `/api/repository-connectors/${id}/profile`,
  );
}

export interface RepositoryItemsParams {
  item_type?: string;
  include_deleted?: boolean;
  extraction_status?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export function listRepositoryItems(
  id: number,
  params: RepositoryItemsParams = {},
): Promise<RepositoryItemsResponse> {
  const search = new URLSearchParams();
  if (params.item_type) search.set("item_type", params.item_type);
  if (params.include_deleted) search.set("include_deleted", "true");
  if (params.extraction_status)
    search.set("extraction_status", params.extraction_status);
  if (params.search) search.set("search", params.search);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiClient.get<RepositoryItemsResponse>(
    `/api/repository-connectors/${id}/items${qs ? `?${qs}` : ""}`,
  );
}
