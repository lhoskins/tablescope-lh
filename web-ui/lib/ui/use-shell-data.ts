"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
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
}

interface ProjectSummaryResponse {
  id: number;
  name: string;
  is_shared: boolean;
  updated_at: string;
  document_count: number;
  query_count: number;
  dashboard_count: number;
  member_count: number;
  data_source_count: number;
  ai_status: string;
}

const ROLE_LABEL: Record<string, string> = {
  root_admin: "Root Admin",
  tenant_admin: "Admin",
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
};

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
          tenantName: me.tenant_name,
          initials: initials(name),
        },
        tenant: {
          name: me.tenant_name,
          slug: me.tenant_slug ?? "",
          initials: initials(me.tenant_name),
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
    aiStatus: toAiStatus(p.ai_status),
    accent: accentFor(id),
  };
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
