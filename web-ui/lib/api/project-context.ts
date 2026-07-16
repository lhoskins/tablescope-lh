import { apiClient } from "@/lib/api-client";

export interface ProjectBusinessContextSettings {
  business_owner_id: number | null;
  business_function: string | null;
  industry: string | null;
  purpose: string | null;
  timezone: string;
  currency: string;
  reporting_cadence: string | null;
  fiscal_year_start_month: number | null;
  ai_context_enabled: boolean;
  ai_instructions: string | null;
  interpretation_notes: string | null;
}

export interface ProjectBusinessContext extends ProjectBusinessContextSettings {
  id: number;
  project_id: number;
  tenant_id: number;
  version: number;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectGoal {
  id: number;
  tenant_id: number;
  project_id: number;
  title: string;
  description: string | null;
  category: string | null;
  priority: string;
  owner_id: number | null;
  status: string;
  start_date: string | null;
  target_date: string | null;
  linked_metric_ids: number[];
  linked_risk_ids: number[];
  active: boolean;
  position: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectMetricTarget {
  id: number;
  tenant_id: number;
  project_id: number;
  metric_id: number;
  target_type: string;
  target_value: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  comparison_operator: string | null;
  warning_threshold: number | null;
  critical_threshold: number | null;
  baseline: number | null;
  effective_start: string | null;
  effective_end: string | null;
  period: string | null;
  notes: string | null;
  status: string;
  active: boolean;
  position: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectMetric {
  id: number;
  tenant_id: number;
  project_id: number;
  name: string;
  description: string | null;
  business_definition: string | null;
  unit: string | null;
  format: string | null;
  directionality: string;
  aggregation: string;
  source_type: string | null;
  source_query_id: number | null;
  source_mapping: unknown;
  expression: string | null;
  owner_id: number | null;
  cadence: string | null;
  active: boolean;
  position: number;
  version: number;
  targets: ProjectMetricTarget[];
  created_at: string;
  updated_at: string;
}

export interface ProjectRisk {
  id: number;
  tenant_id: number;
  project_id: number;
  title: string;
  description: string | null;
  category: string | null;
  likelihood: string | null;
  impact: string | null;
  severity: string | null;
  owner_id: number | null;
  mitigation: string | null;
  contingency: string | null;
  status: string;
  review_date: string | null;
  source_reference: string | null;
  linked_goal_ids: number[];
  linked_metric_ids: number[];
  active: boolean;
  position: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectContextPermissions {
  can_edit: boolean;
  can_archive: boolean;
}

export interface ProjectContext {
  settings: ProjectBusinessContext | null;
  goals: ProjectGoal[];
  metrics: ProjectMetric[];
  risks: ProjectRisk[];
  permissions: ProjectContextPermissions;
  version: number;
  last_updated_at: string | null;
}

export interface ProjectContextAuditEvent {
  id: number;
  tenant_id: number;
  project_id: number;
  actor_user_id: number | null;
  actor_type: string;
  event_type: string;
  entity_type: string;
  entity_id: number | null;
  previous_value: unknown;
  new_value: unknown;
  version: number | null;
  created_at: string;
}

export interface ProjectContextAuditList {
  items: ProjectContextAuditEvent[];
  total: number;
}

export interface SettingsUpdateRequest extends Partial<ProjectBusinessContextSettings> {
  expected_version?: number;
}

export interface GoalCreateRequest {
  title: string;
  description?: string | null;
  category?: string | null;
  priority?: string;
  owner_id?: number | null;
  status?: string;
  start_date?: string | null;
  target_date?: string | null;
  linked_metric_ids?: number[];
  linked_risk_ids?: number[];
}

export interface GoalUpdateRequest extends Partial<GoalCreateRequest> {
  active?: boolean;
  expected_version?: number;
}

export interface MetricCreateRequest {
  name: string;
  description?: string | null;
  business_definition?: string | null;
  unit?: string | null;
  format?: string | null;
  directionality?: string;
  aggregation?: string;
  source_type?: string | null;
  source_query_id?: number | null;
  source_mapping?: unknown;
  expression?: string | null;
  owner_id?: number | null;
  cadence?: string | null;
  targets?: MetricTargetCreateRequest[];
}

export interface MetricUpdateRequest extends Partial<MetricCreateRequest> {
  active?: boolean;
  expected_version?: number;
}

export interface MetricTargetCreateRequest {
  target_type: string;
  target_value?: number | null;
  lower_bound?: number | null;
  upper_bound?: number | null;
  comparison_operator?: string | null;
  warning_threshold?: number | null;
  critical_threshold?: number | null;
  baseline?: number | null;
  effective_start?: string | null;
  effective_end?: string | null;
  period?: string | null;
  notes?: string | null;
  status?: string;
}

export interface MetricTargetUpdateRequest extends Partial<MetricTargetCreateRequest> {
  active?: boolean;
  expected_version?: number;
}

export interface RiskCreateRequest {
  title: string;
  description?: string | null;
  category?: string | null;
  likelihood?: string | null;
  impact?: string | null;
  severity?: string | null;
  owner_id?: number | null;
  mitigation?: string | null;
  contingency?: string | null;
  status?: string;
  review_date?: string | null;
  source_reference?: string | null;
  linked_goal_ids?: number[];
  linked_metric_ids?: number[];
}

export interface RiskUpdateRequest extends Partial<RiskCreateRequest> {
  active?: boolean;
  expected_version?: number;
}

export interface ReorderRequest {
  ids: number[];
  expected_version?: number;
}

export function getProjectContext(projectId: number | string): Promise<ProjectContext> {
  return apiClient.get<ProjectContext>(`/api/projects/${projectId}/context`);
}

export function updateProjectSettings(
  projectId: number | string,
  body: SettingsUpdateRequest,
): Promise<ProjectBusinessContext> {
  return apiClient.put<ProjectBusinessContext>(
    `/api/projects/${projectId}/context/settings`,
    body,
  );
}

export function listGoals(projectId: number | string): Promise<ProjectGoal[]> {
  return apiClient.get<ProjectGoal[]>(`/api/projects/${projectId}/goals`);
}

export function createGoal(projectId: number | string, body: GoalCreateRequest): Promise<ProjectGoal> {
  return apiClient.post<ProjectGoal>(`/api/projects/${projectId}/goals`, body);
}

export function updateGoal(
  projectId: number | string,
  goalId: number,
  body: GoalUpdateRequest,
): Promise<ProjectGoal> {
  return apiClient.patch<ProjectGoal>(`/api/projects/${projectId}/goals/${goalId}`, body);
}

export function deleteGoal(projectId: number | string, goalId: number): Promise<void> {
  return apiClient.delete(`/api/projects/${projectId}/goals/${goalId}`);
}

export function reorderGoals(
  projectId: number | string,
  body: ReorderRequest,
): Promise<{ ok: boolean }> {
  return apiClient.patch<{ ok: boolean }>(`/api/projects/${projectId}/goals/reorder`, body);
}

export function listMetrics(projectId: number | string): Promise<ProjectMetric[]> {
  return apiClient.get<ProjectMetric[]>(`/api/projects/${projectId}/metrics`);
}

export function createMetric(
  projectId: number | string,
  body: MetricCreateRequest,
): Promise<ProjectMetric> {
  return apiClient.post<ProjectMetric>(`/api/projects/${projectId}/metrics`, body);
}

export function updateMetric(
  projectId: number | string,
  metricId: number,
  body: MetricUpdateRequest,
): Promise<ProjectMetric> {
  return apiClient.patch<ProjectMetric>(`/api/projects/${projectId}/metrics/${metricId}`, body);
}

export function deleteMetric(projectId: number | string, metricId: number): Promise<void> {
  return apiClient.delete(`/api/projects/${projectId}/metrics/${metricId}`);
}

export function reorderMetrics(
  projectId: number | string,
  body: ReorderRequest,
): Promise<{ ok: boolean }> {
  return apiClient.patch<{ ok: boolean }>(`/api/projects/${projectId}/metrics/reorder`, body);
}

export function createTarget(
  projectId: number | string,
  metricId: number,
  body: MetricTargetCreateRequest,
): Promise<ProjectMetricTarget> {
  return apiClient.post<ProjectMetricTarget>(
    `/api/projects/${projectId}/metrics/${metricId}/targets`,
    body,
  );
}

export function updateTarget(
  projectId: number | string,
  metricId: number,
  targetId: number,
  body: MetricTargetUpdateRequest,
): Promise<ProjectMetricTarget> {
  return apiClient.patch<ProjectMetricTarget>(
    `/api/projects/${projectId}/metrics/${metricId}/targets/${targetId}`,
    body,
  );
}

export function deleteTarget(
  projectId: number | string,
  metricId: number,
  targetId: number,
): Promise<void> {
  return apiClient.delete(`/api/projects/${projectId}/metrics/${metricId}/targets/${targetId}`);
}

export function listRisks(projectId: number | string): Promise<ProjectRisk[]> {
  return apiClient.get<ProjectRisk[]>(`/api/projects/${projectId}/risks`);
}

export function createRisk(
  projectId: number | string,
  body: RiskCreateRequest,
): Promise<ProjectRisk> {
  return apiClient.post<ProjectRisk>(`/api/projects/${projectId}/risks`, body);
}

export function updateRisk(
  projectId: number | string,
  riskId: number,
  body: RiskUpdateRequest,
): Promise<ProjectRisk> {
  return apiClient.patch<ProjectRisk>(`/api/projects/${projectId}/risks/${riskId}`, body);
}

export function deleteRisk(projectId: number | string, riskId: number): Promise<void> {
  return apiClient.delete(`/api/projects/${projectId}/risks/${riskId}`);
}

export function reorderRisks(
  projectId: number | string,
  body: ReorderRequest,
): Promise<{ ok: boolean }> {
  return apiClient.patch<{ ok: boolean }>(`/api/projects/${projectId}/risks/reorder`, body);
}

export function listProjectContextAudit(
  projectId: number | string,
  params: { limit?: number; offset?: number } = {},
): Promise<ProjectContextAuditList> {
  const search = new URLSearchParams();
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiClient.get<ProjectContextAuditList>(
    `/api/projects/${projectId}/context/audit${qs ? `?${qs}` : ""}`,
  );
}
