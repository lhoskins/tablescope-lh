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
} from "../types";import { Dashboard } from "./dashboard";



export function useProjectDashboards(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "dashboards"],
    queryFn: () =>
      apiClient.get<Dashboard[]>(`/api/projects/${projectId}/dashboards`),
    enabled: Boolean(projectId),
  });
}