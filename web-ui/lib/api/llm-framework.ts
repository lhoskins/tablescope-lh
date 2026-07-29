import { apiClient } from "@/lib/api-client";

export interface LLMFrameworkStatus {
  enabled: boolean;
  hf_catalog_enabled: boolean;
  gguf_only: boolean;
  deployment_enabled: boolean;
  two_person_approval_required: boolean;
  auto_rollback_enabled: boolean;
  manifest_signing_key_fingerprint: string;
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
