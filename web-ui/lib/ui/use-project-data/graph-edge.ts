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
import { RelationshipStrength } from "./relationship-strength";
import { ConnectorStyle } from "./connector-style";



export interface GraphEdge {
  id: GraphId;
  source: GraphId;
  target: GraphId;
  type: string;
  confidence: number;
  evidence: string;
  validationStatus?: string;
  // Relationship evidence classification (connector-style policy). Absent on
  // legacy responses, in which case the canvas falls back to confidence.
  relationshipStrength?: RelationshipStrength;
  connectorStyle?: ConnectorStyle;
  displayByDefault?: boolean;
  evidenceBasis?: string;
  evidenceSummary?: string;
}