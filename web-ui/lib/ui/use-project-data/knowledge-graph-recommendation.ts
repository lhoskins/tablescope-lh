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
} from "../types";import { KnowledgeGraphSeverity } from "./knowledge-graph-severity";



export interface KnowledgeGraphRecommendation {
  id: string;
  nodeKey: string;
  title: string;
  summary: string;
  severity: KnowledgeGraphSeverity;
  confidence: number;
}