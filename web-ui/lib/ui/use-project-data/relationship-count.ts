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
} from "../types";import { ProjectAsset } from "./project-asset";
import { metaCount } from "./meta-count";



export function relationshipCount(asset: ProjectAsset): number | null {
  return metaCount(asset.ai_metadata, [
    "relationship_count",
    "relationships",
    "links",
  ]);
}