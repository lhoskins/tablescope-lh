"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightConfidenceFactor {
  code: string;
  label: string;
  status: "passed" | "partial" | "failed" | "not_applicable";
  score: number;
  weight: number;
  evidence: string;
}