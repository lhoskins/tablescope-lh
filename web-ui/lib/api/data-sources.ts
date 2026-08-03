"use client";

import { apiClient } from "@/lib/api-client";

export interface PreflightDeleteResponse {
  safe: boolean;
  archived: boolean;
  blockers: { category: string; message: string }[];
  active_query_dependencies: { id: number; name: string }[];
}

const uploadBase = (viewName: string) =>
  `/api/upload/datasources/${encodeURIComponent(viewName)}`;

export function preflightDeleteFileSource(
  viewName: string,
): Promise<PreflightDeleteResponse> {
  return apiClient.get<PreflightDeleteResponse>(
    `${uploadBase(viewName)}/preflight-delete`,
  );
}

export function archiveFileSource(
  viewName: string,
  archived = true,
): Promise<{ archived: boolean }> {
  return apiClient.patch<{ archived: boolean }>(
    `${uploadBase(viewName)}/archive`,
    { archived },
  );
}

export function deleteFileSource(viewName: string): Promise<{ status: string }> {
  return apiClient.delete<{ status: string }>(uploadBase(viewName));
}

export function preflightDeleteDatabaseSource(
  sourceId: number,
): Promise<PreflightDeleteResponse> {
  return apiClient.get<PreflightDeleteResponse>(
    `/api/database-sources/${sourceId}/preflight-delete`,
  );
}

export function archiveDatabaseSource(
  sourceId: number,
  archived = true,
): Promise<{ archived: boolean }> {
  return apiClient.patch<{ archived: boolean }>(
    `/api/database-sources/${sourceId}/archive`,
    { archived },
  );
}

export function deleteDatabaseSource(
  sourceId: number,
): Promise<{ status: string }> {
  return apiClient.delete<{ status: string }>(`/api/database-sources/${sourceId}`);
}

export function preflightDeleteSaasSource(
  sourceId: number,
): Promise<PreflightDeleteResponse> {
  return apiClient.get<PreflightDeleteResponse>(
    `/api/saas-sources/${sourceId}/preflight-delete`,
  );
}

export function archiveSaasSource(
  sourceId: number,
  archived = true,
): Promise<{ archived: boolean }> {
  return apiClient.patch<{ archived: boolean }>(
    `/api/saas-sources/${sourceId}/archive`,
    { archived },
  );
}

export function deleteSaasSource(
  sourceId: number,
): Promise<{ status: string }> {
  return apiClient.delete<{ status: string }>(`/api/saas-sources/${sourceId}`);
}
