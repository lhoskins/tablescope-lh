"use client";

import { apiClient } from "@/lib/api-client";

export interface AssignableSource {
  database_data_source_id: number;
  database_connection_id: number | null;
  display_name: string;
  db_type: string;
  host: string;
  database_name: string;
  table_name: string;
}

export interface AssignableUser {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
}

export interface Assignment {
  id: number;
  database_data_source_id: number;
  database_connection_id: number | null;
  assigned_user_id: number;
  assigned_user_email: string | null;
  assigned_user_name: string | null;
  friendly_name: string;
  read_only: boolean;
  is_active: boolean;
  assigned_by: number | null;
  assigned_by_name: string | null;
  datasource_name: string | null;
  db_type: string | null;
  created_at: string | null;
}

export function listAssignableSources(): Promise<AssignableSource[]> {
  return apiClient.get<AssignableSource[]>(
    "/api/admin/assignable-db-sources",
  );
}

export function listAssignableUsers(): Promise<AssignableUser[]> {
  return apiClient.get<AssignableUser[]>("/api/admin/assignable-users");
}

export function listAssignments(): Promise<Assignment[]> {
  return apiClient.get<Assignment[]>("/api/admin/data-source-assignments");
}

export function createAssignment(body: {
  database_data_source_id: number;
  assigned_user_ids: number[];
  friendly_name: string;
  read_only: boolean;
}): Promise<Assignment[]> {
  return apiClient.post<Assignment[]>(
    "/api/admin/data-source-assignments",
    body,
  );
}

export function updateAssignment(
  id: number,
  body: { friendly_name?: string; read_only?: boolean; is_active?: boolean },
): Promise<Assignment> {
  return apiClient.put<Assignment>(
    `/api/admin/data-source-assignments/${id}`,
    body,
  );
}

export function deleteAssignment(id: number): Promise<void> {
  return apiClient.delete(`/api/admin/data-source-assignments/${id}`);
}
