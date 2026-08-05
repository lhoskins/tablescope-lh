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
} from "../types";import { GraphResponse } from "./graph-response";



export function useProjectGraph(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "graph"],
    queryFn: () =>
      apiClient.get<GraphResponse>(`/api/projects/${projectId}/graph`),
    enabled: Boolean(projectId),
  });
}