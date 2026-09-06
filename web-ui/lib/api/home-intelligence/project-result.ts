"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightCard } from "./insight-card";



export interface ProjectResult {
  projectId: string;
  projectName: string;
  projectColor: string;
  insights: InsightCard[];
  /** True while a background Analyze/Refresh run for this project is still
   * in progress -- survives navigation, so a caller that revisits the page
   * mid-run can still show the in-progress indicator instead of stale data
   * with no explanation. */
  stale?: boolean;
}