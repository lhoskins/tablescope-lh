"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiClient } from "@/lib/api-client";
import { useCurrentUser, useProjectSummaries } from "../use-shell-data";
import type {
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";
import type {
  CurrentUser,
  ProjectSummary,
  TenantSummary,
} from "../types";import { FALLBACK_USER } from "./fallback-user";
import { FALLBACK_TENANT } from "./fallback-tenant";



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
  const otherProjects = all.filter((p) => p.id !== projectId);

  return {
    user: identity?.user ?? FALLBACK_USER,
    tenant: identity?.tenant ?? FALLBACK_TENANT,
    project,
    otherProjects,
    counts: {
      queries: project?.queryCount,
      documents: project?.documentCount,
      actionCount: project?.actionCount,
    },
    isLoading,
  };
}