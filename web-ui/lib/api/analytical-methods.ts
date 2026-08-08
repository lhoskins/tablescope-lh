import { apiClient } from "@/lib/api-client";

export interface MethodCatalogOverview {
  id: number;
  catalog_key: string;
  name: string;
  description: string | null;
  source_document: string | null;
  is_active: boolean;
  version: { id: number; version: string; status: string; method_count: number } | null;
  methods_total: number;
  executable_total: number;
  by_tier: Record<string, number>;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
}

export interface MethodSummary {
  id: number;
  method_id: string;
  display_name: string;
  category: string | null;
  subcategory: string | null;
  tier: number;
  status: string;
  summary: string | null;
  supported_intents: string[];
  is_executable: boolean;
  execution_engine: string;
  executor_key: string | null;
  implementation_available: boolean;
}

export interface MethodDetail extends MethodSummary {
  applicability_condition: string | null;
  selection_rules: unknown[];
  rejection_rules: unknown[];
  required_checks: unknown[];
  fallback_methods: unknown[];
  output_contract: Record<string, unknown>;
  method_card: Record<string, unknown>;
  llm_guardrails: unknown[];
  executor_key: string | null;
  dependencies: unknown[];
}

export interface MethodListResponse {
  total: number;
  limit: number;
  offset: number;
  methods: MethodSummary[];
}

export interface MethodListParams {
  tier?: number;
  status?: string;
  category?: string;
  q?: string;
  executable?: boolean;
  limit?: number;
  offset?: number;
}

export function getMethodCatalogOverview(): Promise<MethodCatalogOverview> {
  return apiClient.get<MethodCatalogOverview>("/api/ai/methods/catalog");
}

export function listAnalyticalMethods(
  params: MethodListParams = {},
): Promise<MethodListResponse> {
  const search = new URLSearchParams();
  if (params.tier != null) search.set("tier", String(params.tier));
  if (params.status) search.set("status", params.status);
  if (params.category) search.set("category", params.category);
  if (params.q) search.set("q", params.q);
  if (params.executable != null) search.set("executable", String(params.executable));
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiClient.get<MethodListResponse>(`/api/ai/methods${qs ? `?${qs}` : ""}`);
}

export function getAnalyticalMethod(methodId: string): Promise<MethodDetail> {
  return apiClient.get<MethodDetail>(`/api/ai/methods/${encodeURIComponent(methodId)}`);
}

export function activateAnalyticalMethod(methodId: string): Promise<MethodDetail> {
  return apiClient.post<MethodDetail>(`/api/ai/methods/${encodeURIComponent(methodId)}/activate`, {});
}

export function deactivateAnalyticalMethod(methodId: string): Promise<MethodDetail> {
  return apiClient.post<MethodDetail>(`/api/ai/methods/${encodeURIComponent(methodId)}/deactivate`, {});
}
