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
} from "../types";import { GraphNode } from "./graph-node";
import { GraphEdge } from "./graph-edge";
import { KnowledgeGraphInsightCard } from "./knowledge-graph-insight-card";
import { KnowledgeGraphGap } from "./knowledge-graph-gap";
import { KnowledgeGraphRecommendation } from "./knowledge-graph-recommendation";
import { KnowledgeGraphStats } from "./knowledge-graph-stats";



export interface KnowledgeGraphResponse {
  centerNode: GraphNode | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  insightCards: KnowledgeGraphInsightCard[];
  gaps: KnowledgeGraphGap[];
  recommendedActions: KnowledgeGraphRecommendation[];
  tracePaths: {
    id: string;
    fromNodeKey: string;
    nodeIds: number[];
    edgeIds: number[];
  }[];
  stats: KnowledgeGraphStats;
  lens?: string;
  minConfidence?: number;
  includeInferred?: boolean;
  pipeline_version?: string;
  generated_at?: string;
  /** ISO timestamp of the cached snapshot the payload was built from. */
  lastUpdated?: string;
  snapshotId?: number;
  /** True when served from the cached snapshot (false right after a refresh). */
  isCached?: boolean;
}