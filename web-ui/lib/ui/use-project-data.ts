"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useCurrentUser, useProjectSummaries } from "./use-shell-data";
import type {
  CurrentUser,
  ProjectSummary,
  TenantSummary,
} from "./types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

/**
 * Assembles everything the project-mode app shell needs: identity, the active
 * project's summary, the other projects (for the sidebar switcher) and the
 * per-project sidebar counts.
 */
export function useProjectShell(projectId: string) {
  const { data: identity } = useCurrentUser();
  const { data: summaries, isLoading } = useProjectSummaries();

  const all = summaries ?? [];
  const project = all.find((p) => p.id === projectId) ?? null;
  const otherProjects = all.filter((p) => p.id !== projectId).slice(0, 6);

  return {
    user: identity?.user ?? FALLBACK_USER,
    tenant: identity?.tenant ?? FALLBACK_TENANT,
    project,
    otherProjects,
    counts: {
      queries: project?.queryCount,
      documents: project?.documentCount,
    },
    isLoading,
  };
}

// ── Queries ──────────────────────────────────────────────────────────

export interface SavedQuery {
  id: number;
  project_id: number;
  owner_id: number | null;
  name: string;
  description: string | null;
  left_datasource: string | null;
  right_datasource: string | null;
  join_type: string | null;
  left_column: string | null;
  right_column: string | null;
  sql_text: string | null;
  ai_generated: boolean;
  is_shared: boolean;
  run_count: number;
  last_run_at: string | null;
  avg_runtime_ms: number | null;
  created_at: string;
  updated_at: string;
}

export function useProjectQueries(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "queries"],
    queryFn: () =>
      apiClient.get<SavedQuery[]>(`/api/projects/${projectId}/queries`),
    enabled: Boolean(projectId),
  });
}

// ── Dashboards ───────────────────────────────────────────────────────

export interface Dashboard {
  id: number;
  project_id: number;
  owner_id: number | null;
  tenant_id: number;
  name: string;
  description: string | null;
  status: string;
  config: Record<string, unknown>;
  ai_generated: boolean;
  view_count: number;
  created_at: string;
  updated_at: string;
}

export function widgetCount(config: Record<string, unknown>): number {
  const widgets = config?.widgets;
  return Array.isArray(widgets) ? widgets.length : 0;
}

export function useProjectDashboards(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "dashboards"],
    queryFn: () =>
      apiClient.get<Dashboard[]>(`/api/projects/${projectId}/dashboards`),
    enabled: Boolean(projectId),
  });
}

// ── Documents (project assets) ───────────────────────────────────────

export interface ProjectAsset {
  id: number;
  project_id: number;
  asset_type: string;
  source_type: string;
  title: string;
  description: string | null;
  filename: string;
  original_filename: string | null;
  content_type: string | null;
  file_extension: string | null;
  file_size_bytes: number | null;
  visibility: string;
  status: string;
  ai_status: string;
  ai_summary: string | null;
  ai_metadata: Record<string, unknown>;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

function metaCount(meta: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = meta?.[key];
    if (typeof value === "number") return value;
    if (Array.isArray(value)) return value.length;
  }
  return null;
}

export function relationshipCount(asset: ProjectAsset): number | null {
  return metaCount(asset.ai_metadata, [
    "relationship_count",
    "relationships",
    "links",
  ]);
}

export function extractionCount(asset: ProjectAsset): number | null {
  return metaCount(asset.ai_metadata, [
    "extraction_count",
    "extractions",
    "clauses",
    "entities",
    "kpis",
  ]);
}

export function useProjectDocuments(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "assets"],
    queryFn: () =>
      apiClient.get<ProjectAsset[]>(`/api/projects/${projectId}/assets`),
    enabled: Boolean(projectId),
  });
}

// ── Data sources ─────────────────────────────────────────────────────

export interface DataSource {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType: string;
  dbType: string | null;
  connectorType?: string | null;
  id?: number;
  fileMetaId?: number | null;
  ownerId?: number | null;
  columnTypes?: unknown[];
  aiMetadata?: Record<string, unknown> | null;
  archived?: boolean;
}

export function columnLabel(col: unknown): { name: string; type: string } {
  if (col && typeof col === "object") {
    const rec = col as Record<string, unknown>;
    const name =
      typeof rec.name === "string"
        ? rec.name
        : typeof rec.column === "string"
          ? rec.column
          : "";
    const type =
      typeof rec.type === "string"
        ? rec.type
        : typeof rec.dataType === "string"
          ? rec.dataType
          : "";
    if (name) return { name, type };
  }
  if (Array.isArray(col)) {
    return { name: String(col[0] ?? ""), type: String(col[1] ?? "") };
  }
  return { name: String(col ?? ""), type: "" };
}

export function useProjectDataSources(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "datasources"],
    queryFn: () =>
      apiClient.get<DataSource[]>(`/api/projects/${projectId}/datasources`),
    enabled: Boolean(projectId),
  });
}

// ── Members ──────────────────────────────────────────────────────────

export interface ProjectMember {
  project_id: number;
  user_id: number;
  role: string;
  is_active: boolean;
  email: string;
  display_name: string | null;
}

export function useProjectMembers(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "members"],
    queryFn: () =>
      apiClient.get<ProjectMember[]>(`/api/projects/${projectId}/members`),
    enabled: Boolean(projectId),
  });
}

// ── Relationship graph ───────────────────────────────────────────────

export interface GraphNode {
  id: number;
  type: string;
  label: string;
  source_type: string | null;
  source_id: number | null;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  id: number;
  source: number;
  target: number;
  type: string;
  confidence: number;
  evidence: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function useProjectGraph(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "graph"],
    queryFn: () =>
      apiClient.get<GraphResponse>(`/api/projects/${projectId}/graph`),
    enabled: Boolean(projectId),
  });
}

// ── Metadata catalog ─────────────────────────────────────────────────

export interface CatalogField {
  name: string;
  type: string | null;
  ai_description: string | null;
  null_percent: number | null;
  distinct_count: number | null;
  sample_values: unknown[];
  include_in_ai: boolean;
}

export interface CatalogTable {
  data_source_id: number;
  name: string;
  source: string | null;
  row_count: number | null;
  field_count: number | null;
  ai_summary: string | null;
  ai_quality_summary: string | null;
  status: string;
  last_synced: string | null;
  fields: CatalogField[];
}

export interface CatalogDocument {
  id: number;
  title: string;
  type: string;
  status: string;
  clauses: number;
  relationships: number;
}

export interface MetadataCatalog {
  tables: CatalogTable[];
  documents: CatalogDocument[];
}

export function useProjectMetadataCatalog(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "metadata-catalog"],
    queryFn: () =>
      apiClient.get<MetadataCatalog>(
        `/api/projects/${projectId}/metadata-catalog`,
      ),
    enabled: Boolean(projectId),
  });
}

// ── Activity / audit feed ────────────────────────────────────────────

export interface ActivityEvent {
  id: string;
  ts: string;
  category: string;
  label: string;
  title: string;
  detail: string | null;
  actor: string;
}

export interface ActivityStats {
  total_events: number;
  ai_actions: number;
  active_users: number;
  isolation_violations: number;
}

export interface ProjectActivity {
  events: ActivityEvent[];
  stats: ActivityStats;
}

export function useProjectActivity(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "activity"],
    queryFn: () =>
      apiClient.get<ProjectActivity>(`/api/projects/${projectId}/activity`),
    enabled: Boolean(projectId),
  });
}

// ── AI assistant ─────────────────────────────────────────────────────

export interface AiAskResponse {
  answer: string;
  model_used: string;
  request_id: string;
  context_summary: Record<string, unknown>;
  audit_id: number | null;
}

export function askProjectAi(
  projectId: string,
  question: string,
  scope = "project",
): Promise<AiAskResponse> {
  return apiClient.post<AiAskResponse>("/api/ai/ask", {
    project_id: Number(projectId),
    question,
    scope,
  });
}
