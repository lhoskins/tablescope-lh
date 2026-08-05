"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface VizDecision {
  chartType: string;
  chartStyle: string;
  xField?: string | null;
  yField?: string | null;
  y2Field?: string | null;
  valueFormat: string;
  topN?: number | null;
  reason: string;
  confidence: number;
}