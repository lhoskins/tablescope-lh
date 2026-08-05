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
} from "../types";import { useProjectDataSources } from "./use-project-data-sources";



/** Archived project data sources only (file, database and SaaS). */
export function useProjectArchivedDataSources(projectId: string) {
  const { data, isLoading } = useProjectDataSources(projectId, true);
  return {
    data: useMemo(() => (data ?? []).filter((s) => s.archived), [data]),
    isLoading,
  };
}