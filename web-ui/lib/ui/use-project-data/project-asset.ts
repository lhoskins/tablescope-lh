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


// ── Documents (project assets) ───────────────────────────────────────

export interface ProjectAsset {
  id: number;
  project_id: number;
  asset_type: string;
  source_type: string;
  title: string;
  description: string | null;
  filename: string;
  original_filename: string | null;
  content_type: string | null;
  file_extension: string | null;
  file_size_bytes: number | null;
  visibility: string;
  status: string;
  ai_status: string;
  ai_summary: string | null;
  ai_metadata: Record<string, unknown>;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}