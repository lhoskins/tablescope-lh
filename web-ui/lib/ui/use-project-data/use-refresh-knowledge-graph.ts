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
} from "../types";import { KnowledgeGraphRefreshResult } from "./knowledge-graph-refresh-result";



/**
 * Manually rebuild the project's Knowledge Graph snapshot, then invalidate the
 * cached graph query so the canvas re-reads the fresh snapshot. Mirrors the AI
 * Home refresh: node clicks read the cached snapshot; only this rebuilds it.
 */
export function useRefreshKnowledgeGraph(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiClient.post<KnowledgeGraphRefreshResult>(
        `/api/projects/${projectId}/graph/refresh`,
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["project", projectId, "knowledge-graph"],
      });
    },
  });
}