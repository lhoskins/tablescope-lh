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
} from "../types";import { ProjectMember } from "./project-member";



export function useUpdateProjectMemberRole(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { userId: number; role: string }) =>
      apiClient.put<ProjectMember>(
        `/api/projects/${projectId}/members/${vars.userId}/role`,
        { role: vars.role },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["project", projectId, "members"] }),
  });
}