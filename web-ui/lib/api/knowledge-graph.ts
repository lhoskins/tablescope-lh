import { apiClient } from "@/lib/api-client";

export interface ChangeSetItem {
  entity_type: string;
  entity_id?: number | null;
  action?: "added" | "updated" | "removed" | "schema_change";
  change_scope?: "local" | "structural" | "schema";
  details?: Record<string, unknown>;
}

export interface KnowledgeGraphBuild {
  id: number;
  graph_id: number;
  tenant_id: number;
  project_id: number;
  trigger_type: string;
  build_type: string;
  requested_by: number | null;
  status: string;
  stage: string;
  progress: number;
  error_code: string | null;
  safe_error_message: string | null;
  retry_attempt: number;
  worker_id: string | null;
  candidate_version_id: number | null;
  source_checkpoint: Record<string, unknown> | null;
  affected_entity_summary: Record<string, unknown> | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeGraphVersion {
  id: number;
  graph_id: number;
  tenant_id: number;
  project_id: number;
  version_number: number;
  build_id: number | null;
  status: string;
  build_type: string;
  source_fingerprint: string | null;
  node_count: number;
  edge_count: number;
  disconnected_component_count: number;
  storage_reference: string | null;
  created_by: number | null;
  activated_at: string | null;
  superseded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeGraphHealthCheck {
  id: number;
  graph_id: number | null;
  version_id: number | null;
  tenant_id: number;
  project_id: number;
  status: string;
  check_type: string;
  node_count: number;
  edge_count: number;
  orphan_ratio: number | null;
  disconnected_components: number;
  structural_checks: Record<string, unknown> | null;
  source_alignment: Record<string, unknown> | null;
  dependency_checks: Record<string, unknown> | null;
  warnings: string[] | null;
  errors: string[] | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface KnowledgeGraphStatus {
  project_id: number;
  graph_id: number | null;
  lifecycle_status: string;
  enabled: boolean;
  active_version_id: number | null;
  active_version_number: number | null;
  last_healthy_version_id: number | null;
  last_healthy_version_number: number | null;
  current_source_fingerprint: string | null;
  active_source_fingerprint: string | null;
  last_successful_build_at: string | null;
  last_health_check_at: string | null;
  active_node_count: number;
  active_edge_count: number;
  health_status: string;
  has_active_version: boolean;
  builds: KnowledgeGraphBuild[];
  versions: KnowledgeGraphVersion[];
}

export interface KnowledgeGraphRebuildResponse {
  build: KnowledgeGraphBuild;
  build_type: string;
  enqueued: boolean;
}

export interface ExecutiveInsightDependency {
  ready: boolean;
  mode: "full" | "limited" | "blocked";
  graph_status: string;
  graph_version_id: number | null;
  graph_version_number: number | null;
  active_node_count: number;
  active_edge_count: number;
  warnings: string[];
  blocking_reasons: string[];
  disclosure: string;
  health_status: string;
}

export const knowledgeGraphApi = {
  status: (projectId: string | number): Promise<KnowledgeGraphStatus> =>
    apiClient.get<KnowledgeGraphStatus>(`/api/projects/${projectId}/knowledge-graph/status`),

  rebuild: (projectId: string | number): Promise<KnowledgeGraphRebuildResponse> =>
    apiClient.post<KnowledgeGraphRebuildResponse>(`/api/projects/${projectId}/knowledge-graph/rebuild`, {}),

  rebuildIncremental: (
    projectId: string | number,
    changeSet: ChangeSetItem[],
    reason?: string,
  ): Promise<KnowledgeGraphRebuildResponse> =>
    apiClient.post<KnowledgeGraphRebuildResponse>(
      `/api/projects/${projectId}/knowledge-graph/rebuild/incremental`,
      { change_set: changeSet, reason },
    ),

  listBuilds: (projectId: string | number): Promise<KnowledgeGraphBuild[]> =>
    apiClient.get<KnowledgeGraphBuild[]>(`/api/projects/${projectId}/knowledge-graph/builds`),

  getBuild: (projectId: string | number, buildId: number): Promise<KnowledgeGraphBuild> =>
    apiClient.get<KnowledgeGraphBuild>(`/api/projects/${projectId}/knowledge-graph/builds/${buildId}`),

  runHealthCheck: (projectId: string | number): Promise<KnowledgeGraphHealthCheck> =>
    apiClient.post<KnowledgeGraphHealthCheck>(`/api/projects/${projectId}/knowledge-graph/health-check`, {}),

  getHealth: (projectId: string | number): Promise<KnowledgeGraphHealthCheck> =>
    apiClient.get<KnowledgeGraphHealthCheck>(`/api/projects/${projectId}/knowledge-graph/health`),

  listVersions: (projectId: string | number): Promise<KnowledgeGraphVersion[]> =>
    apiClient.get<KnowledgeGraphVersion[]>(`/api/projects/${projectId}/knowledge-graph/versions`),

  executiveInsightDependency: (
    projectId: string | number,
  ): Promise<ExecutiveInsightDependency> =>
    apiClient.get<ExecutiveInsightDependency>(
      `/api/projects/${projectId}/knowledge-graph/dependencies/executive-insight`,
    ),
};
