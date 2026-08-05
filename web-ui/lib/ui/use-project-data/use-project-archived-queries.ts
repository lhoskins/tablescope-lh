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
} from "../types";import { SavedQuery } from "./saved-query";



/** Archived queries only — powers the Queries "Archive" folder. */
export function useProjectArchivedQueries(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId, "queries", "archived"],
    queryFn: async () => {
      const all = await apiClient.get<SavedQuery[]>(
        `/api/projects/${projectId}/queries?include_archived=true`,
      );
      return all.filter((q) => q.is_archived);
    },
    enabled: Boolean(projectId),
  });
}