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


// ── Queries ──────────────────────────────────────────────────────────

export interface SavedQuery {
  id: number;
  project_id: number;
  owner_id: number | null;
  name: string;
  description: string | null;
  left_datasource: string | null;
  right_datasource: string | null;
  join_type: string | null;
  left_column: string | null;
  right_column: string | null;
  sql_text: string | null;
  ai_generated: boolean;
  is_shared: boolean;
  run_count: number;
  last_run_at: string | null;
  avg_runtime_ms: number | null;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  owner_name: string | null;
  origin: string;
  origin_label: string;
  source_name: string | null;
  has_outgoing_scope: boolean;
  outgoing_scope_count: number;
  has_incoming_scope: boolean;
  incoming_scope_count: number;
  has_active_scope: boolean;
  active_scope_count: number;
}