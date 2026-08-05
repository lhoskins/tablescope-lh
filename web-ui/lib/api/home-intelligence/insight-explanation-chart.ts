"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightExplanationChart {
  chartType: string;
  labelColumn: string | null;
  valueColumn: string | null;
  valueColumn2: string | null;
}