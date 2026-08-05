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
import { KnowledgeGraphCardCategory } from "./knowledge-graph-card-category";



export interface KnowledgeGraphInsightCard {
  id: string;
  nodeKey: string;
  category: KnowledgeGraphCardCategory;
  severity: KnowledgeGraphSeverity;
  title: string;
  summary: string;
  businessQuestion?: string;
  businessImpact?: string;
  confidence: number;
  evidencePath: string[];
  sourceDocuments: string[];
  sourceTables: string[];
  sourceQueries: string[];
  sourceDashboards: string[];
  supportedKpis: string[];
  recommendedAction?: string;
  traceToEvidence: {
    nodeIds: GraphId[];
    edgeIds: GraphId[];
    nodeKeys?: string[];
  };
}