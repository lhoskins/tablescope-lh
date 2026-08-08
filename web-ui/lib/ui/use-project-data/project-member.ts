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


// ── Members ──────────────────────────────────────────────────────────

export interface ProjectMember {
  project_id: number;
  user_id: number;
  role: string;
  is_active: boolean;
  email: string;
  display_name: string | null;
}