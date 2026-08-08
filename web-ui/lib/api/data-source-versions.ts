"use client";

import { apiClient } from "@/lib/api-client";

export interface SourceVersion {
  id: number;
  versionNumber: number;
  status: "staged" | "active" | "archived" | "failed" | "rolled_back";
  updateMode: string;
  originalFilename: string;
  checksum: string | null;
  sizeBytes: number | null;
  rowCount: number | null;
  columnTypes: { name?: string; field?: string; type?: string }[];
  compatibility: Record<string, unknown>;
  uploaderId: number | null;
  replacedVersionId: number | null;
  activatedAt: string | null;
  createdAt: string | null;
  errorMessage: string | null;
}

export interface SchemaCompatibility {
  addedColumns: string[];
  removedColumns: string[];
  typeChangedColumns: { column: string; from: string; to: string }[];
  blockers: string[];
  compatible: boolean;
  dependencies: { id: number; name: string }[];
  warnings: string[];
  currentFileName: string;
  proposedFileName: string;
  currentRowCount: number | null;
  proposedRowCount: number | null;
  currentChecksum: string | null;
  proposedChecksum: string | null;
  updateMode: string;
}

export interface PreflightResponse {
  status: string;
  viewName: string;
  version: SourceVersion;
  activeVersion: SourceVersion;
  compatibility: SchemaCompatibility;
  canActivate: boolean;
}

const base = (viewName: string) =>
  `/api/upload/datasources/${encodeURIComponent(viewName)}`;

/** Stage a replacement file and get the schema/dependency preflight. */
export function preflightSourceUpdate(
  viewName: string,
  file: File,
): Promise<PreflightResponse> {
  return apiClient.upload<PreflightResponse>(
    `${base(viewName)}/versions/preflight`,
    file,
  );
}

export function activateSourceVersion(
  viewName: string,
  versionId: number,
): Promise<{ status: string; fileName: string; version: SourceVersion }> {
  return apiClient.post(`${base(viewName)}/versions/${versionId}/activate`, {});
}

export function listSourceVersions(viewName: string): Promise<SourceVersion[]> {
  return apiClient.get<SourceVersion[]>(`${base(viewName)}/versions`);
}

export function rollbackSourceVersion(
  viewName: string,
  versionId: number,
): Promise<{ status: string; version: SourceVersion }> {
  return apiClient.post(`${base(viewName)}/versions/${versionId}/rollback`, {});
}
