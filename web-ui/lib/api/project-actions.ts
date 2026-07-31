import { apiClient } from "@/lib/api-client";

export type ProjectActionStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "completed"
  | "cancelled";

export type ProjectActionPriority = "low" | "medium" | "high" | "critical";

export type ProjectActionView = "board" | "my-actions" | "timeline" | "archived";

export type ProjectActionGroupBy =
  | "status"
  | "priority"
  | "owner"
  | "due_state"
  | "source_type"
  | "none";

export type ProjectActionSortBy =
  | "updated"
  | "created"
  | "due_date"
  | "priority"
  | "progress"
  | "title";

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
  effort_points: number | null;
  created_by_user_id: number | null;
  updated_by_user_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  completed_at: string | null;
  lock_version: number;
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
  lock_version: number;
  subtasks: ProjectActionSubtask[];
}

export interface ProjectActionSummary {
  active: number;
  overdue: number;
  avg_progress: number;
  risk_mitigations_completed: number;
}

export interface ProjectActionGroupSummary {
  group: string;
  label: string;
  count: number;
  overdue_count: number;
  avg_progress: number;
}

export interface ProjectActionBoardSummary extends ProjectActionSummary {
  groups: ProjectActionGroupSummary[];
}

export interface ProjectActionListItem {
  id: number;
  title: string;
  description: string | null;
  status: ProjectActionStatus;
  priority: ProjectActionPriority;
  owner_user_id: number | null;
  owner_name: string | null;
  due_date: string | null;
  percent_complete: number;
  source_type: string;
  source_insight_id: string | null;
  source_insight_fingerprint: string | null;
  source_insight_type: string | null;
  source_insight_title: string | null;
  source_insight_snapshot: Record<string, unknown> | null;
  risk_impact: string | null;
  active_subtasks: number;
  total_subtasks: number;
  required_subtasks: number;
  completed_required_subtasks: number;
  comment_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  archived_at: string | null;
  lock_version: number;
}

export interface ProjectActionListResponse {
  items: ProjectActionListItem[];
  total: number;
  summary: ProjectActionBoardSummary;
}

export interface ProjectActionFilters {
  status?: ProjectActionStatus;
  priority?: ProjectActionPriority;
  owner_user_id?: number;
  overdue?: boolean;
  due_from?: string;
  due_to?: string;
  source_type?: string;
  source_insight_type?: string;
  source_insight_fingerprint?: string;
  risk_impact?: string;
  has_incomplete_required_subtasks?: boolean;
  q?: string;
  include_archived?: boolean;
  sort_by?: ProjectActionSortBy;
  sort_direction?: "asc" | "desc";
  group_by?: ProjectActionGroupBy;
  limit?: number;
  offset?: number;
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
  effort_points?: number | null;
}

export interface UpdateProjectActionPayload {
  title?: string;
  description?: string | null;
  status?: ProjectActionStatus;
  priority?: ProjectActionPriority;
  owner_user_id?: number | null;
  due_date?: string | null;
  archived_at?: string | null;
  expected_version?: number;
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
  effort_points?: number | null;
  archived_at?: string | null;
  expected_version?: number;
}

export interface ProjectActionBulkPayload {
  action_ids: number[];
  expected_versions: Record<number, number>;
  status?: ProjectActionStatus;
  priority?: ProjectActionPriority;
  owner_user_id?: number | null;
  due_date?: string | null;
}

export interface ProjectActionBulkResult {
  action_id: number;
  success: boolean;
  lock_version?: number | null;
  error?: string | null;
}

export interface ProjectActionBulkResponse {
  results: ProjectActionBulkResult[];
}

export interface ProjectActionComment {
  id: number;
  tenant_id: number;
  project_id: number;
  action_id: number;
  author_user_id: number | null;
  author_name: string | null;
  body: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
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
    apiClient.get(
      `/api/projects/${projectId}/actions${buildQs(
        (filters ?? {}) as Record<string, string | number | boolean | undefined>,
      )}`,
    ),

  board: (
    projectId: string,
    filters?: ProjectActionFilters,
  ): Promise<ProjectActionListResponse> =>
    apiClient.get(
      `/api/projects/${projectId}/actions/board${buildQs(
        (filters ?? {}) as Record<string, string | number | boolean | undefined>,
      )}`,
    ),

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

  draftFromInsight: (
    projectId: string,
    body: {
      insight_type: string;
      title: string;
      summary: string;
      recommended_action?: string | null;
      severity?: string;
      sources?: { tables?: string[]; documents?: string[] };
      supporting_sources?: string[];
      explanation?: Record<string, unknown> | null;
    },
  ): Promise<{
    title: string;
    description: string;
    subtasks: CreateProjectActionSubtaskPayload[];
    success_criteria: {
      name: string;
      description: string;
      target_value: string | number | null;
      directionality: string;
      cadence: string;
      unit: string;
      format: string;
    }[];
    model_used: string;
    request_id: string;
  }> => apiClient.post(`/api/projects/${projectId}/actions/draft-from-insight`, body),

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

  archive: (
    projectId: string,
    actionId: number,
    expected_version?: number,
  ): Promise<{ status: string; id: number; lock_version: number }> =>
    apiClient.delete(
      `/api/projects/${projectId}/actions/${actionId}${
        expected_version !== undefined ? `?expected_version=${expected_version}` : ""
      }`,
    ),

  restore: (projectId: string, actionId: number): Promise<ProjectAction> =>
    apiClient.post(`/api/projects/${projectId}/actions/${actionId}/restore`, {}),

  bulkUpdate: (
    projectId: string,
    payload: ProjectActionBulkPayload,
  ): Promise<ProjectActionBulkResponse> =>
    apiClient.patch(`/api/projects/${projectId}/actions/bulk`, payload),

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
    expected_version?: number,
  ): Promise<{ status: string; id: number; lock_version: number }> =>
    apiClient.delete(
      `/api/projects/${projectId}/actions/${actionId}/subtasks/${subtaskId}${
        expected_version !== undefined ? `?expected_version=${expected_version}` : ""
      }`,
    ),

  listComments: (
    projectId: string,
    actionId: number,
  ): Promise<ProjectActionComment[]> =>
    apiClient.get(`/api/projects/${projectId}/actions/${actionId}/comments`),

  createComment: (
    projectId: string,
    actionId: number,
    body: { body: string },
  ): Promise<ProjectActionComment> =>
    apiClient.post(`/api/projects/${projectId}/actions/${actionId}/comments`, body),

  updateComment: (
    projectId: string,
    actionId: number,
    commentId: number,
    body: { body: string },
  ): Promise<ProjectActionComment> =>
    apiClient.patch(
      `/api/projects/${projectId}/actions/${actionId}/comments/${commentId}`,
      body,
    ),

  archiveComment: (
    projectId: string,
    actionId: number,
    commentId: number,
  ): Promise<{ status: string; id: number }> =>
    apiClient.delete(
      `/api/projects/${projectId}/actions/${actionId}/comments/${commentId}`,
    ),
};
