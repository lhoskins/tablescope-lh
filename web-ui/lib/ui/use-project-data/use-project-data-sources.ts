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
} from "../types";import { DataSource } from "./data-source";



export function useProjectDataSources(
  projectId: string,
  includeArchived = false,
) {
  return useQuery({
    queryKey: ["project", projectId, "datasources", { includeArchived }],
    queryFn: () =>
      apiClient.get<DataSource[]>(
        `/api/projects/${projectId}/datasources?include_archived=${includeArchived}`,
      ),
    enabled: Boolean(projectId),
  });
}