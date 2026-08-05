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
} from "../types";import { ProjectActivity } from "./project-activity";



export function useProjectActivity(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "activity"],
    queryFn: () =>
      apiClient.get<ProjectActivity>(`/api/projects/${projectId}/activity`),
    enabled: Boolean(projectId),
  });
}