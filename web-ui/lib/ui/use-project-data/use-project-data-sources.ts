"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { DataSource } from "./data-source";

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
