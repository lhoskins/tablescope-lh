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
} from "../types";import { AddableUser } from "./addable-user";



/**
 * Tenant users eligible to be added to the project. The endpoint is restricted
 * to project managers, so a successful fetch doubles as the signal that the
 * current user is allowed to manage members.
 */
export function useAddableUsers(projectId: string, enabled = true) {
  return useQuery({
    queryKey: ["project", projectId, "addable-users"],
    queryFn: () =>
      apiClient.get<AddableUser[]>(
        `/api/projects/${projectId}/addable-users`,
      ),
    enabled: Boolean(projectId) && enabled,
    retry: false,
  });
}