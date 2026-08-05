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
} from "../types";


export function useRemoveProjectMember(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    // "Remove" deactivates the member (the backend keeps a permanent-delete step
    // for inactive members so contributed datasources can be moved back first).
    mutationFn: (userId: number) =>
      apiClient.put(
        `/api/projects/${projectId}/members/${userId}/deactivate`,
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId, "members"] });
      qc.invalidateQueries({
        queryKey: ["project", projectId, "addable-users"],
      });
    },
  });
}