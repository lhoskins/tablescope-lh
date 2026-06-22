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
  | "database-connectors"
  | "data-source-builder"
  | "documents"
  | "dashboards"
  | "relationship-map"
  | "reference-library"
  | "company-reference-library"
  | "integrations"
  | "audit-log"
  | "settings"
  | "admin-users"
  | "admin-tenants"
  | "admin-data-planes"
  // Project-mode nav
  | "overview"
  | "project-data-sources"
  | "project-queries"
  | "project-scopes"
  | "project-dashboards"
  | "project-documents"
  | "project-ai-assistant"
  | "project-relationship-map"
  | "project-metadata-catalog"
  | "project-reference-library"
  | "project-audit-log";

export interface TenantSummary {
  name: string;
  slug: string;
  initials: string;
}

export interface CurrentUser {
  name: string;
  email: string;
  /** Display label for the role (e.g. "Admin", "Editor"). */
  role: string;
  /** Raw role identifier from the API (e.g. "tenant_admin", "editor"). */
  rawRole?: string;
  isSuperAdmin?: boolean;
  tenantName: string;
  initials: string;
}
