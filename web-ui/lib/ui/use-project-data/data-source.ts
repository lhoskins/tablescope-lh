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


// ── Data sources ─────────────────────────────────────────────────────

export interface DataSource {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType: string;
  dbType: string | null;
  connectorType?: string | null;
  id?: number;
  fileMetaId?: number | null;
  ownerId?: number | null;
  columnTypes?: unknown[];
  aiMetadata?: Record<string, unknown> | null;
  archived?: boolean;
  archivedAt?: string | null;
}