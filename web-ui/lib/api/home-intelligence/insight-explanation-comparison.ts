"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightExplanationComparison {
  type: string;
  baselineValue: number;
  currentValue: number;
  baselineLabel: string;
  currentLabel: string;
  field: string;
}