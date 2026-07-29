import { apiClient } from "@/lib/api-client";

export interface LLMFrameworkStatus {
  enabled: boolean;
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

export function getLLMFrameworkStatus(): Promise<LLMFrameworkStatus> {
  return apiClient.get<LLMFrameworkStatus>("/api/llm-framework/status");
}

export function getLLMInventory(): Promise<LLMInventory> {
  return apiClient.get<LLMInventory>("/api/llm-framework/inventory");
}

export function getLLMCapabilities(): Promise<LLMCapabilities> {
  return apiClient.get<LLMCapabilities>("/api/llm-framework/capabilities");
}
