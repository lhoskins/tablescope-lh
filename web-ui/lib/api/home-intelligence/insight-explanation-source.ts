"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightExplanationSource {
  projectId: string | number;
  projectName: string;
  dataSourceId: string | null;
  dataSourceName: string | null;
  tables: string[];
  fields: string[];
}