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
} from "../types";import { MetadataCatalog } from "./metadata-catalog";



export function useProjectMetadataCatalog(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "metadata-catalog"],
    queryFn: () =>
      apiClient.get<MetadataCatalog>(
        `/api/projects/${projectId}/metadata-catalog`,
      ),
    enabled: Boolean(projectId),
  });
}