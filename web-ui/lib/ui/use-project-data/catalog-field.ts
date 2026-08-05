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


// ── Metadata catalog ─────────────────────────────────────────────────

export interface CatalogField {
  name: string;
  type: string | null;
  ai_description: string | null;
  null_percent: number | null;
  distinct_count: number | null;
  sample_values: unknown[];
  include_in_ai: boolean;
}