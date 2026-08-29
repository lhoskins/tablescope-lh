import { apiClient } from "@/lib/api-client";
import type { WorkspaceResourceType } from "@/components/tablescope/project/workspace/workspace-tabs-storage";

/** How a card is laid out on the workspace canvas. */
export type WorkspaceCardViewMode = "card" | "row" | "full";

export interface WorkspaceCard {
  id: number;
  resource_type: WorkspaceResourceType;
  /** Stored as a string to match `WorkspaceTab.id`; numeric for the resource
   *  types the backend can resolve (table/dashboard/document/data_source). */
  resource_id: string;
  view_mode: WorkspaceCardViewMode;
  position: number;
  added_at?: string | null;
  /** Resolved display name, or null when the resource no longer exists. */
  label?: string | null;
}

export interface Workspace {
  id: number;
  tenant_id: number;
  project_id: number;
  owner_user_id: number | null;
  name: string;
  visibility: "private" | "shared_project";
  published_at: string | null;
  created_at: string;
  updated_at: string;
  cards: WorkspaceCard[];
}

export interface CreateWorkspaceRequest {
  name: string;
  cards?: { resource_type: WorkspaceResourceType; resource_id: string }[];
}

export interface UpdateWorkspaceRequest {
  name?: string;
  /** Full replacement of the card list — adds, removals, reorders and
   *  view_mode changes are all expressed as the new desired list. */
  cards?: {
    resource_type: WorkspaceResourceType;
    resource_id: string;
    view_mode: WorkspaceCardViewMode;
    position?: number;
  }[];
}

function base(projectId: number | string): string {
  return `/api/projects/${projectId}/workspaces`;
}

export function listWorkspaces(projectId: number | string): Promise<Workspace[]> {
  return apiClient.get<Workspace[]>(base(projectId));
}

export function getWorkspace(
  projectId: number | string,
  workspaceId: number,
): Promise<Workspace> {
  return apiClient.get<Workspace>(`${base(projectId)}/${workspaceId}`);
}

export function createWorkspace(
  projectId: number | string,
  data: CreateWorkspaceRequest,
): Promise<Workspace> {
  return apiClient.post<Workspace>(base(projectId), data);
}

export function updateWorkspace(
  projectId: number | string,
  workspaceId: number,
  data: UpdateWorkspaceRequest,
): Promise<Workspace> {
  return apiClient.patch<Workspace>(`${base(projectId)}/${workspaceId}`, data);
}

export function publishWorkspace(
  projectId: number | string,
  workspaceId: number,
): Promise<Workspace> {
  return apiClient.post<Workspace>(`${base(projectId)}/${workspaceId}/publish`, {});
}

export function unpublishWorkspace(
  projectId: number | string,
  workspaceId: number,
): Promise<Workspace> {
  return apiClient.post<Workspace>(`${base(projectId)}/${workspaceId}/unpublish`, {});
}

export function deleteWorkspace(
  projectId: number | string,
  workspaceId: number,
): Promise<void> {
  return apiClient.delete(`${base(projectId)}/${workspaceId}`);
}
