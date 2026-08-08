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
} from "../types";import { KnowledgeGraphResponse } from "./knowledge-graph-response";
import { KnowledgeGraphParams } from "./knowledge-graph-params";



/**
 * Node-centric Insight-First Knowledge Graph. Passing a `lens` (always set by
 * the Knowledge Graph screen) makes the backend return the enriched payload
 * with insight cards, gaps, recommendations and trace paths.
 */
export function useKnowledgeGraph(
  projectId: string,
  params: KnowledgeGraphParams,
) {
  const query: Record<string, string> = {
    lens: params.lens ?? "insight-first",
    min_confidence: String(params.minConfidence ?? 0.7),
    include_inferred: String(params.includeInferred ?? false),
    severity: params.severity ?? "all",
  };
  if (params.centerNode) query.center_node = params.centerNode;
  if (params.refresh) query.refresh = "true";
  const qs = new URLSearchParams(query).toString();

  return useQuery({
    queryKey: ["project", projectId, "knowledge-graph", query],
    queryFn: () =>
      apiClient.get<KnowledgeGraphResponse>(
        `/api/projects/${projectId}/graph?${qs}`,
      ),
    enabled: Boolean(projectId),
  });
}