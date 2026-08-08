"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightExplanationConfidence {
  level: "low" | "medium" | "high" | null;
  score: number | null;
  basis: string;
}