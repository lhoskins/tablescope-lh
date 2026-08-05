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
} from "../types";import { GraphId } from "./graph-id";
import { KnowledgeGraphSeverity } from "./knowledge-graph-severity";



export interface GraphNode {
  id: GraphId;
  type: string;
  label: string;
  source_type: string | null;
  source_id: number | null;
  properties: Record<string, unknown>;
  // Node-centric Knowledge Graph metadata (optional; absent on legacy responses).
  graphKey?: string;
  layer?: string;
  displayGroup?: string;
  severity?: KnowledgeGraphSeverity;
  summary?: string;
  businessValue?: string;
  businessQuestion?: string;
  confidence?: number | null;
  isCenterEligible?: boolean;
  recommendedLens?: string;
}