import { apiClient } from "@/lib/api-client";

export type ProjectActionStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "completed"
  | "cancelled";

export type ProjectActionPriority = "low" | "medium" | "high" | "critical";

export interface ProjectActionSubtask {
  id: number;
  action_id: number;
  tenant_id: number;
  project_id: number;
  title: string;
  description: string | null;
  status: ProjectActionStatus;
  percent_complete: number;
  owner_user_id: number | null;
  due_date: string | null;
  position: number;
  is_required: boolean;
  created_by_user_id: number | null;
  updated_by_user_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface ProjectAction {
  id: number;
  tenant_id: number;
  project_id: number;
  title: string;
  description: string | null;
  status: ProjectActionStatus;
  priority: ProjectActionPriority;
  owner_user_id: number | null;
  due_date: string | null;
  started_at: string | null;
  completed_at: string | null;
  percent_complete: number;
  source_type: string;
  source_insight_id: string | null;
  source_insight_fingerprint: string | null;
  source_insight_type: string | null;
  source_insight_title: string | null;
  source_insight_snapshot: Record<string, unknown> | null;
  created_by_user_id: number | null;
  updated_by_user_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  subtasks: ProjectActionSubtask[];
}

export interface ProjectActionListItem {
  id: number;
  title: string;
  status: ProjectActionStatus;
  priority: ProjectActionPriority;
  owner_user_id: number | null;
  owner_name: string | null;
  due_date: string | null;
  percent_complete: number;
  source_insight_type: string | null;
  source_insight_title: string | null;
  source_insight_snapshot: Record<string, unknown> | null;
  active_subtasks: number;
  total_subtasks: number;
  updated_at: string;
  archived_at: string | null;
}

export interface ProjectActionListResponse {
  items: ProjectActionListItem[];
  total: number;
}

export interface CreateProjectActionPayload {
  title: string;
  description?: string | null;
  status?: ProjectActionStatus;
  priority?: ProjectActionPriority;
  owner_user_id?: number | null;
  due_date?: string | null;
  source_type?: string;
  source_insight_id?: string | null;
  source_insight_type?: string | null;
  source_insight_title?: string | null;
  source_insight_snapshot?: Record<string, unknown> | null;
  initial_subtasks?: CreateProjectActionSubtaskPayload[];
  idempotency_key?: string | null;
}

export interface CreateProjectActionSubtaskPayload {
  title: string;
  description?: string | null;
  status?: ProjectActionStatus;
  percent_complete?: number;
  owner_user_id?: number | null;
  due_date?: string | null;
  is_required?: boolean;
}

export interface UpdateProjectActionPayload {
  title?: string;
  description?: string | null;
  status?: ProjectActionStatus;
  priority?: ProjectActionPriority;
  owner_user_id?: number | null;
  due_date?: string | null;
  archived_at?: string | null;
}

export interface UpdateProjectActionSubtaskPayload {
  title?: string;
  description?: string | null;
  status?: ProjectActionStatus;
  percent_complete?: number;
  owner_user_id?: number | null;
  due_date?: string | null;
  position?: number;
  is_required?: boolean;
  archived_at?: string | null;
}

export interface InsightSnapshotForAction {
  title?: string;
  summary?: string;
  severity?: string;
  project_id?: string;
  project_name?: string;
  insight_type?: string;
  recommended_action?: string;
  sources?: { tables?: string[]; documents?: string[] };
  evidence?: string[];
  supporting_sources?: string[];
}

function buildQs(params: Record<string, string | number | boolean | undefined>) {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    out.set(k, String(v));
  }
  const s = out.toString();
  return s ? `?${s}` : "";
}

export const projectActionsApi = {
  list: (
    projectId: string,
    filters?: {
      status?: ProjectActionStatus;
      priority?: ProjectActionPriority;
      owner_user_id?: number;
      overdue?: boolean;
      source_insight_fingerprint?: string;
      q?: string;
      include_archived?: boolean;
      limit?: number;
      offset?: number;
    },
  ): Promise<ProjectActionListResponse> =>
    apiClient.get(`/api/projects/${projectId}/actions${buildQs(filters ?? {})}`),

  countForInsight: (
    projectId: string,
    body: {
      source_insight_id?: string | null;
      source_insight_type?: string | null;
      source_insight_title?: string | null;
      source_insight_snapshot?: Record<string, unknown> | null;
    },
  ): Promise<{ count: number; action_ids: number[] }> =>
    apiClient.post(`/api/projects/${projectId}/actions:count-for-insight`, body),

  get: (projectId: string, actionId: number): Promise<ProjectAction> =>
    apiClient.get(`/api/projects/${projectId}/actions/${actionId}`),

  create: (
    projectId: string,
    payload: CreateProjectActionPayload,
  ): Promise<ProjectAction> =>
    apiClient.post(`/api/projects/${projectId}/actions`, payload),

  update: (
    projectId: string,
    actionId: number,
    payload: UpdateProjectActionPayload,
  ): Promise<ProjectAction> =>
    apiClient.patch(`/api/projects/${projectId}/actions/${actionId}`, payload),

  archive: (projectId: string, actionId: number): Promise<{ status: string; id: number }> =>
    apiClient.delete(`/api/projects/${projectId}/actions/${actionId}`),

  createSubtask: (
    projectId: string,
    actionId: number,
    payload: CreateProjectActionSubtaskPayload,
  ): Promise<ProjectActionSubtask> =>
    apiClient.post(
      `/api/projects/${projectId}/actions/${actionId}/subtasks`,
      payload,
    ),

  updateSubtask: (
    projectId: string,
    actionId: number,
    subtaskId: number,
    payload: UpdateProjectActionSubtaskPayload,
  ): Promise<ProjectActionSubtask> =>
    apiClient.patch(
      `/api/projects/${projectId}/actions/${actionId}/subtasks/${subtaskId}`,
      payload,
    ),

  archiveSubtask: (
    projectId: string,
    actionId: number,
    subtaskId: number,
  ): Promise<{ status: string; id: number }> =>
    apiClient.delete(
      `/api/projects/${projectId}/actions/${actionId}/subtasks/${subtaskId}`,
    ),
};
