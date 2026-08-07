import { apiClient } from "@/lib/api-client";

export interface LLMFrameworkStatus {
  enabled: boolean;
  hf_catalog_enabled: boolean;
  gguf_only: boolean;
  deployment_enabled: boolean;
  two_person_approval_required: boolean;
  auto_rollback_enabled: boolean;
  manifest_signing_key_fingerprint: string;
  embedding_migration_enabled: boolean;
  fp16_conversion_enabled: boolean;
  dynamic_routing_enabled: boolean;
  embedding_recall_threshold: number;
}

export interface RuntimeTarget {
  id: number;
  name: string;
  runtime_type: string;
  host: string;
  version: string | null;
  status: string;
  is_reachable: boolean;
  last_seen_at: string | null;
  max_loaded_models: number | null;
  keep_alive_minutes: number | null;
  labels: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ArtifactFile {
  id: number;
  filename: string;
  size_bytes: number | null;
  hash_algorithm: string;
  hash_value: string;
}

export interface LicenseApproval {
  id: number;
  status: string;
  license_type: string | null;
  license_url: string | null;
  notes: string | null;
  approved_at: string | null;
}

export interface ModelArtifact {
  id: number;
  name: string;
  publisher: string | null;
  repo_url: string | null;
  commit_sha: string | null;
  quantization: string | null;
  format: string;
  size_bytes: number | null;
  status: string;
  manifest_public_key_fingerprint: string | null;
  quarantine_reason: string | null;
  verified_at: string | null;
  created_at: string;
  updated_at: string;
  files?: ArtifactFile[];
  license_approval?: LicenseApproval | null;
}

export interface Installation {
  id: number;
  artifact_id: number;
  target_id: number;
  status: string;
  installed_path: string | null;
  installed_at: string | null;
  activated_at: string | null;
  rolled_back_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RoutingProfile {
  id: number;
  capability: string;
  target_id: number;
  installation_id: number | null;
  is_active: boolean;
  priority: number;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Deployment {
  id: number;
  installation_id: number;
  artifact_id: number;
  artifact_name: string;
  target_id: number;
  target_name: string;
  requested_by_user_id: number | null;
  approved_by_user_id: number | null;
  status: string;
  previous_deployment_id: number | null;
  stabilized_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: number;
  actor_user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface LLMInventory {
  targets: RuntimeTarget[];
  artifacts: ModelArtifact[];
  installations: Installation[];
  routing_profiles: RoutingProfile[];
}

export interface LLMCapabilities {
  capabilities: string[];
  gguf_only: boolean;
  deployment_enabled: boolean;
}

export interface CatalogFile {
  filename: string;
  size: number | null;
  lfs: boolean;
}

export interface CatalogSearchResult {
  repo_id: string;
  publisher: string;
  name: string;
  tags: string[];
  license: string | null;
  description: string | null;
  downloads: number | null;
  likes: number | null;
  last_modified: string | null;
  gguf_files: CatalogFile[];
  gguf_total_bytes: number | null;
}

export interface CatalogDetail extends CatalogSearchResult {
  commit_sha: string | null;
  license_url: string | null;
  readme: string | null;
  siblings: CatalogFile[];
}

export interface StageArtifactPayload {
  repo_url: string;
  quantization?: string | null;
  name?: string | null;
}

export interface StageArtifactResponse {
  artifact_id: number;
  job_id: string;
  status: string;
}

export interface PreflightResponse {
  artifact_id: number;
  target_id: number;
  target_reachable: boolean;
  disk_ok: boolean;
  slot_ok: boolean;
  detail: string | null;
}

export interface InstallResponse {
  installation_id: number;
  deployment_id: number;
  status: string;
  job_id: string | null;
}

export interface DeploymentResponse {
  id: number;
  installation_id: number;
  requested_by_user_id: number | null;
  approved_by_user_id: number | null;
  status: string;
  previous_deployment_id: number | null;
  stabilized_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActivateRequest {
  capability: string;
  target_id: number;
}

export interface RoutingProfileRequest {
  capability: string;
  target_id: number;
  installation_id: number;
  priority?: number;
  is_active?: boolean;
  expected_version?: number | null;
}

export interface RuntimeTargetCreate {
  name: string;
  host: string;
  runtime_type?: string;
  version?: string | null;
  max_loaded_models?: number | null;
  keep_alive_minutes?: number | null;
  labels?: Record<string, unknown>;
}

export function getLLMFrameworkStatus(): Promise<LLMFrameworkStatus> {
  return apiClient.get<LLMFrameworkStatus>("/api/llm-framework/status");
}

export function getLLMInventory(): Promise<LLMInventory> {
  return apiClient.get<LLMInventory>("/api/llm-framework/inventory");
}

export function getLLMCapabilities(): Promise<LLMCapabilities> {
  return apiClient.get<LLMCapabilities>("/api/llm-framework/capabilities");
}

export function getLLMArtifact(artifactId: number): Promise<ModelArtifact> {
  return apiClient.get<ModelArtifact>(`/api/llm-framework/artifacts/${artifactId}`);
}

export function searchLLMCatalog(q: string, limit = 20): Promise<CatalogSearchResult[]> {
  return apiClient.get<CatalogSearchResult[]>(
    `/api/llm-framework/catalog/search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
}

export function getLLMCatalogDetail(repoUrl: string): Promise<CatalogDetail> {
  return apiClient.get<CatalogDetail>(
    `/api/llm-framework/catalog/detail?repo_url=${encodeURIComponent(repoUrl)}`
  );
}

export function stageLLMArtifact(payload: StageArtifactPayload): Promise<StageArtifactResponse> {
  return apiClient.post<StageArtifactResponse>("/api/llm-framework/artifacts/stage", payload);
}

export function releaseLLMArtifactQuarantine(artifactId: number): Promise<{ artifact_id: number; previous_status: string; status: string }> {
  return apiClient.post<{ artifact_id: number; previous_status: string; status: string }>(
    `/api/llm-framework/artifacts/${artifactId}/quarantine-release`,
    {}
  );
}

export function preflightLLMInstall(artifactId: number, targetId: number): Promise<PreflightResponse> {
  return apiClient.post<PreflightResponse>(`/api/llm-framework/artifacts/${artifactId}/preflight`, {
    target_id: targetId,
  });
}

export function installLLMArtifact(artifactId: number, targetId: number): Promise<InstallResponse> {
  return apiClient.post<InstallResponse>(`/api/llm-framework/artifacts/${artifactId}/install`, {
    target_id: targetId,
  });
}

export function approveLLMDeployment(deploymentId: number): Promise<{ deployment_id: number; status: string }> {
  return apiClient.post<{ deployment_id: number; status: string }>(
    `/api/llm-framework/deployments/${deploymentId}/approve`,
    {}
  );
}

export function activateLLMDeployment(deploymentId: number, request: ActivateRequest): Promise<{ deployment_id: number; status: string; capability: string; target_id: number }> {
  return apiClient.post<{ deployment_id: number; status: string; capability: string; target_id: number }>(
    `/api/llm-framework/deployments/${deploymentId}/activate`,
    request
  );
}

export function rollbackLLMDeployment(deploymentId: number): Promise<{ deployment_id: number; status: string }> {
  return apiClient.post<{ deployment_id: number; status: string }>(
    `/api/llm-framework/deployments/${deploymentId}/rollback`,
    {}
  );
}

export function upsertLLMRoutingProfile(request: RoutingProfileRequest): Promise<RoutingProfile> {
  return apiClient.put<RoutingProfile>("/api/llm-framework/routing", request);
}

export interface EmbeddingMigration {
  id: number;
  tenant_id: number;
  artifact_id: number;
  source_collection: string;
  target_collection: string;
  embedding_model: string;
  embedding_dim: number;
  status: string;
  recall_score: number | null;
  points_total: number | null;
  points_indexed: number | null;
  created_at: string;
  updated_at: string;
}

export interface ReindexPayload {
  tenant_id: number;
  embedding_model: string;
  embedding_dim: number;
}

export function reindexLLMArtifact(artifactId: number, payload: ReindexPayload): Promise<{ migration_id: number; status: string; job_id: string | null }> {
  return apiClient.post(`/api/llm-framework/artifacts/${artifactId}/reindex`, payload);
}

export function getLLMEmbeddingMigrations(): Promise<EmbeddingMigration[]> {
  return apiClient.get<EmbeddingMigration[]>("/api/llm-framework/embedding-migrations");
}

export interface ModelConversion {
  id: number;
  source_artifact_id: number;
  output_artifact_id: number | null;
  quantization: string | null;
  status: string;
  converter_version: string | null;
  output_size_bytes: number | null;
  created_at: string;
  updated_at: string;
}

export interface ConvertPayload {
  repo_url: string;
  quantization?: string | null;
  converter_version?: string | null;
}

export function convertLLMCatalogEntry(payload: ConvertPayload): Promise<{ source_artifact_id: number; conversion_id: number; status: string; job_id: string | null }> {
  return apiClient.post("/api/llm-framework/catalog/convert", payload);
}

export function getLLMModelConversions(): Promise<ModelConversion[]> {
  return apiClient.get<ModelConversion[]>("/api/llm-framework/model-conversions");
}

export function getLLMDeployments(): Promise<Deployment[]> {
  return apiClient.get<Deployment[]>("/api/llm-framework/deployments");
}

export function getLLMAuditEvents(): Promise<AuditEvent[]> {
  return apiClient.get<AuditEvent[]>("/api/llm-framework/audit-events");
}

export function registerLLMRuntimeTarget(payload: RuntimeTargetCreate): Promise<RuntimeTarget> {
  return apiClient.post<RuntimeTarget>("/api/llm-framework/runtime-targets", payload);
}
