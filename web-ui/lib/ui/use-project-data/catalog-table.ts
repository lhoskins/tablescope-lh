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
} from "../types";import { CatalogField } from "./catalog-field";



export interface CatalogTable {
  data_source_id: number;
  name: string;
  source: string | null;
  row_count: number | null;
  field_count: number | null;
  ai_summary: string | null;
  ai_quality_summary: string | null;
  status: string;
  last_synced: string | null;
  fields: CatalogField[];
}