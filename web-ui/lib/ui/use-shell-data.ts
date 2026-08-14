"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, getApiBaseUrl } from "@/lib/api-client";
import { initials, toAiStatus } from "./format";
import { accentFor } from "./color";
import type { CurrentUser, ProjectSummary, TenantSummary } from "./types";

interface CurrentUserResponse {
  user_id: number;
  email: string;
  display_name: string | null;
  first_name: string | null;
  last_name: string | null;
  role: string;
  is_super_admin: boolean;
  tenant_id: number;
  tenant_name: string;
  tenant_slug: string | null;
  avatar_url: string | null;
  company_logo_url: string | null;
  voice_input_enabled: boolean;
  chat_attachments_enabled: boolean;
  permissions: string[] | null;
}

interface ProjectSummaryResponse {
  id: number;
  name: string;
  is_shared: boolean;
  updated_at: string;
  document_count: number;
  query_count: number;
  dashboard_count: number;
  action_count: number;
  member_count: number;
  data_source_count: number;
  ai_status: string;
}

// Tenant vocabulary only: legacy `editor`/`viewer` roles were retired and now
// display as "Member" so a deleted/legacy role never lingers in the UI.
const ROLE_LABEL: Record<string, string> = {
  root_admin: "Root Admin",
  tenant_admin: "Admin",
  admin: "Admin",
  db_admin: "DB Admin",
  member: "Member",
  editor: "Member",
  viewer: "Member",
};

/** Resolve a relative served URL to an absolute, browser-fetchable URL. */
function absoluteUrl(url: string | null): string | null {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  return `${getApiBaseUrl()}${url}`;
}

function displayName(u: CurrentUserResponse): string {
  if (u.display_name) return u.display_name;
  const full = [u.first_name, u.last_name].filter(Boolean).join(" ");
  return full || u.email.split("@")[0];
}

export function useCurrentUser() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: async (): Promise<{ user: CurrentUser; tenant: TenantSummary }> => {
      const me = await apiClient.get<CurrentUserResponse>("/api/auth/me");
      const name = displayName(me);
      return {
        user: {
          name,
          email: me.email,
          role: ROLE_LABEL[me.role] ?? me.role,
          rawRole: me.role,
          isSuperAdmin: me.is_super_admin,
          tenantName: me.tenant_name,
          initials: initials(name),
          id: me.user_id,
          avatarUrl: absoluteUrl(me.avatar_url),
          permissions: me.permissions ?? [],
        },
        tenant: {
          name: me.tenant_name,
          slug: me.tenant_slug ?? "",
          initials: initials(me.tenant_name),
          logoUrl: absoluteUrl(me.company_logo_url),
          voiceInputEnabled: me.voice_input_enabled,
          chatAttachmentsEnabled: me.chat_attachments_enabled,
        },
      };
    },
    staleTime: 5 * 60_000,
  });
}

export function mapProjectSummary(p: ProjectSummaryResponse): ProjectSummary {
  const id = String(p.id);
  return {
    id,
    name: p.name,
    visibility: p.is_shared ? "shared" : "private",
    updatedLabel: p.updated_at,
    documentCount: p.document_count,
    queryCount: p.query_count,
    dashboardCount: p.dashboard_count,
    actionCount: p.action_count,
    aiStatus: toAiStatus(p.ai_status),
    accent: accentFor(id),
  };
}

export interface HomeDashboardRow {
  id: number;
  name: string;
  projectId: number;
  projectName: string;
  status: string;
  sharedBy: string;
  ownerId: number | null;
  ownerName: string;
  createdAt: string | null;
}

export interface HomeDocumentRow {
  id: number;
  name: string;
  projectId: number;
  projectName: string;
  aiStatus: string;
  sharedBy: string;
  ownerId: number | null;
  ownerName: string;
  createdAt: string | null;
}

export interface HomeDataSourceRow {
  id: number;
  name: string;
  viewName: string;
  kind: "file" | "database";
  projectId: number;
  projectName: string;
  sharedBy: string;
  createdAt: string | null;
}

export function useAllDashboards() {
  return useQuery({
    queryKey: ["home", "dashboards-all"],
    queryFn: () =>
      apiClient.get<HomeDashboardRow[]>("/api/projects/dashboards-all"),
  });
}

export function useAllDocuments() {
  return useQuery({
    queryKey: ["home", "documents-all"],
    queryFn: () =>
      apiClient.get<HomeDocumentRow[]>("/api/projects/documents-all"),
  });
}

export function useAllDataSources() {
  return useQuery({
    queryKey: ["home", "datasources-all"],
    queryFn: () =>
      apiClient.get<HomeDataSourceRow[]>("/api/projects/datasources-all"),
  });
}

export function deleteProject(projectId: number | string): Promise<void> {
  return apiClient.delete<void>(`/api/projects/${projectId}`);
}

export function updateProject(
  projectId: number | string,
  payload: { name?: string; is_shared?: boolean },
): Promise<unknown> {
  return apiClient.put(`/api/projects/${projectId}`, payload);
}

export function useProjectSummaries(opts?: { recent?: boolean; limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.recent) params.set("recent", "true");
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return useQuery({
    queryKey: ["projects", "summaries", opts?.recent ?? false, opts?.limit ?? 0],
    queryFn: async (): Promise<ProjectSummary[]> => {
      const rows = await apiClient.get<ProjectSummaryResponse[]>(
        `/api/projects/summaries${qs ? `?${qs}` : ""}`,
      );
      return rows.map(mapProjectSummary);
    },
  });
}
