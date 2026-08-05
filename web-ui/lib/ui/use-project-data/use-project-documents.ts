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
} from "../types";import { ProjectAsset } from "./project-asset";



export function useProjectDocuments(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "assets"],
    queryFn: () =>
      apiClient.get<ProjectAsset[]>(`/api/projects/${projectId}/assets`),
    enabled: Boolean(projectId),
  });
}