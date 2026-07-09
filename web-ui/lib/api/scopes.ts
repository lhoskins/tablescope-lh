import { apiClient } from "@/lib/api-client";

export type ScopeSetType = "ai_generated" | "manual";
export type MatchMode = "all" | "any";
export type ScopeDirection = "source_to_target" | "target_to_source";

export interface ScopeSet {
  id: number;
  tenant_id: number;
  project_id: number;
  name: string;
  description: string | null;
  type: ScopeSetType;
  enabled: boolean;
  created_by: number | null;
  creator_name: string | null;
  creator_email: string | null;
  created_at: string | null;
  updated_at: string | null;
  can_delete: boolean;
  scope_count: number;
}

export interface ScopeCanvasTable {
  table_key: string;
  table_name: string | null;
  query_id: number | null;
  datasource_id: number | null;
  x_position: number;
  y_position: number;
  width: number | null;
  height: number | null;
}

export interface ScopeRelationship {
  id?: number | null;
  query_id: number;
  source_field: string;
  source_table: string | null;
  target_query_id: number;
  target_field: string;
  target_table: string | null;
  direction: ScopeDirection;
  match_group_id: string | null;
  match_mode: MatchMode;
  enabled: boolean;
  confidence_score: number | null;
  created_by_ai: boolean;
}

export interface ScopeMap {
  scope_set: ScopeSet;
  tables: ScopeCanvasTable[];
  relationships: ScopeRelationship[];
}

export interface ScopeBuilderTable {
  table_key: string;
  table_name: string;
  query_id: number | null;
  datasource_id: number | null;
  fields: string[];
}

export interface ScopeAISuggestion {
  query_id: number;
  source_field: string;
  source_table: string | null;
  target_query_id: number;
  target_field: string;
  target_table: string | null;
  match_group_id: string | null;
  match_mode: MatchMode;
  confidence_score: number | null;
  rationale: string | null;
}

export interface ScopeMapSavePayload {
  name?: string;
  description?: string | null;
  enabled?: boolean;
  tables: ScopeCanvasTable[];
  relationships: ScopeRelationship[];
}

export const scopesApi = {
  listScopeSets: (projectId: number) =>
    apiClient.get<ScopeSet[]>(`/api/projects/${projectId}/scope_sets`),

  createScopeSet: (
    projectId: number,
    body: { name: string; description?: string | null; type?: ScopeSetType },
  ) =>
    apiClient.post<ScopeSet>(`/api/projects/${projectId}/scope_sets`, body),

  autoGenerateScopes: (projectId: number) =>
    apiClient.post<ScopeSet>(
      `/api/projects/${projectId}/scope_sets/auto-generate`,
      {},
    ),

  // LLM-based directional scope generation (Phase 1 AI + Phase 2 cell
  // validation) across all of the project's saved queries. Writes into the
  // project's "AI Generated Scopes" set, so it appears in listScopeSets.
  generateScopeMap: (projectId: number) =>
    apiClient.post<{
      relationships: unknown[];
      scopes_created: number;
      status: string;
    }>(`/api/ai/project/scope-map/generate`, { project_id: projectId }),

  getScopeSet: (scopeSetId: number) =>
    apiClient.get<ScopeSet>(`/api/scope_sets/${scopeSetId}`),

  updateScopeSet: (
    scopeSetId: number,
    body: { name?: string; description?: string | null; enabled?: boolean },
  ) => apiClient.patch<ScopeSet>(`/api/scope_sets/${scopeSetId}`, body),

  deleteScopeSet: (scopeSetId: number) =>
    apiClient.delete(`/api/scope_sets/${scopeSetId}`),

  getMap: (scopeSetId: number) =>
    apiClient.get<ScopeMap>(`/api/scope_sets/${scopeSetId}/map`),

  saveMap: (scopeSetId: number, body: ScopeMapSavePayload) =>
    apiClient.put<ScopeMap>(`/api/scope_sets/${scopeSetId}/map`, body),

  builderTables: (projectId: number) =>
    apiClient.get<ScopeBuilderTable[]>(
      `/api/projects/${projectId}/scope-builder/tables`,
    ),

  aiSuggest: (scopeSetId: number, queryIds: number[]) =>
    apiClient.post<{ suggestions: ScopeAISuggestion[] }>(
      `/api/scope_sets/${scopeSetId}/ai-suggest`,
      { query_ids: queryIds },
    ),
};
