"use client";

import { useMemo } from "react";
import { useProjectDataSources } from "./use-project-data-sources";

/** Archived project data sources only (file, database and SaaS). */
export function useProjectArchivedDataSources(projectId: string) {
  const { data, isLoading } = useProjectDataSources(projectId, true);
  return {
    data: useMemo(() => (data ?? []).filter((s) => s.archived), [data]),
    isLoading,
  };
}
