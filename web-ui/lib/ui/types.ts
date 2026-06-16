// Shared UI domain types for the Tablescope (Concept A) interface.

export type AiStatus = "ready" | "active" | "indexing" | "idle";

export type ProjectVisibility = "private" | "shared";

export interface ProjectSummary {
  id: string;
  name: string;
  visibility: ProjectVisibility;
  updatedLabel: string;
  documentCount: number;
  queryCount: number;
  dashboardCount: number;
  aiStatus: AiStatus;
  /** Stable accent color derived from the project id (deterministic). */
  accent?: string;
}

export type NavKey =
  // Home-mode nav
  | "home"
  | "projects"
  | "ai-assistant"
  | "activity"
  | "data-connections"
  | "data-sources"
  | "documents"
  | "dashboards"
  | "relationship-map"
  | "integrations"
  | "audit-log"
  | "settings"
  // Project-mode nav
  | "overview"
  | "project-data-sources"
  | "project-queries"
  | "project-dashboards"
  | "project-documents"
  | "project-ai-assistant"
  | "project-relationship-map"
  | "project-metadata-catalog"
  | "project-audit-log";

export interface TenantSummary {
  name: string;
  slug: string;
  initials: string;
}

export interface CurrentUser {
  name: string;
  email: string;
  role: string;
  tenantName: string;
  initials: string;
}
