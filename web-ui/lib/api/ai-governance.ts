import { apiClient } from "@/lib/api-client";

export interface MethodPolicy {
  key: string;
  displayName: string;
  description: string;
  category: string;
  riskLevel: string;
  requiresSql: boolean;
  experimental: boolean;
  enabled: boolean;
  source: "default" | "tenant_override";
  reason: string | null;
  updatedBy: number | null;
  updatedAt: string | null;
}

export interface TenantAIPolicy {
  tenantId: number;
  version: number;
  isDefault: boolean;
  methods: Record<string, MethodPolicy>;
}

export interface MethodCatalogItem {
  key: string;
  displayName: string;
  description: string;
  category: string;
  riskLevel: string;
  requiresSql: boolean;
  experimental: boolean;
  defaultEnabled: boolean;
  supportsFallback: boolean;
  fallbackMethodKeys: string[];
}

export interface MethodCatalogResponse {
  methods: MethodCatalogItem[];
}

export interface UpdateMethodRequest {
  enabled: boolean;
  reason?: string | null;
  expected_version: number;
}

export interface BulkUpdateRequest {
  methods: { method_key: string; enabled: boolean; reason?: string | null }[];
  expected_version: number;
}

export interface AuditEvent {
  id: number;
  tenant_id: number;
  actor_user_id: number | null;
  actor_type: string;
  event_type: string;
  method_key: string | null;
  project_id: number | null;
  conversation_id: number | null;
  turn_id: number | null;
  insight_id: string | null;
  policy_version: number | null;
  previous_value: unknown;
  new_value: unknown;
  decision: string | null;
  reason_code: string | null;
  details: unknown;
  request_id: string | null;
  created_at: string;
}

export interface AuditListResponse {
  total: number;
  limit: number;
  offset: number;
  events: AuditEvent[];
}

export function getAIPolicy(): Promise<TenantAIPolicy> {
  return apiClient.get<TenantAIPolicy>("/api/ai-governance/policy");
}

export function getAICapabilities(): Promise<TenantAIPolicy> {
  return apiClient.get<TenantAIPolicy>("/api/ai-governance/capabilities");
}

export function getMethodCatalog(): Promise<MethodCatalogResponse> {
  return apiClient.get<MethodCatalogResponse>("/api/ai-governance/method-catalog");
}

export function updateMethodPolicy(
  methodKey: string,
  body: UpdateMethodRequest,
): Promise<TenantAIPolicy> {
  return apiClient.patch<TenantAIPolicy>(
    `/api/ai-governance/methods/${encodeURIComponent(methodKey)}`,
    body,
  );
}

export function bulkUpdatePolicy(body: BulkUpdateRequest): Promise<TenantAIPolicy> {
  return apiClient.put<TenantAIPolicy>("/api/ai-governance/policy", body);
}

export function listGovernanceAudit(
  params: {
    event_type?: string;
    method_key?: string;
    decision?: string;
    actor_user_id?: number;
    start?: string;
    end?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<AuditListResponse> {
  const search = new URLSearchParams();
  if (params.event_type) search.set("event_type", params.event_type);
  if (params.method_key) search.set("method_key", params.method_key);
  if (params.decision) search.set("decision", params.decision);
  if (params.actor_user_id != null) search.set("actor_user_id", String(params.actor_user_id));
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiClient.get<AuditListResponse>(
    `/api/ai-governance/audit${qs ? `?${qs}` : ""}`,
  );
}
