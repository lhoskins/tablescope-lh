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


// ── AI assistant ─────────────────────────────────────────────────────

export interface AiAskResponse {
  answer: string;
  model_used: string;
  request_id: string;
  context_summary: Record<string, unknown>;
  audit_id: number | null;
  // M4: shared presentation descriptor + unified envelope (additive).
  presentation?: PresentationDescriptor;
  envelope?: ResponseEnvelope;
}