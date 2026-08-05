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



export interface KnowledgeGraphGap {
  id: string;
  nodeKey: string;
  gapType: string;
  title: string;
  severity: KnowledgeGraphSeverity;
  whyItMatters: string;
  authoritativeSource: string;
  expectedEvidence: string;
  missingOrWeakComponent: string;
  affectedProcesses: string[];
  affectedKpis: string[];
  recommendedAction: string;
  confidence: number;
}