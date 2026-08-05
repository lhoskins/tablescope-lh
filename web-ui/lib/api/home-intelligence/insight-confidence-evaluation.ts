"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightConfidenceFactor } from "./insight-confidence-factor";



export interface InsightConfidenceEvaluation {
  version: number;
  score: number;
  level: "low" | "medium" | "high";
  basis: string;
  factors: InsightConfidenceFactor[];
  caps: string[];
  gaps: string[];
  whatWouldIncreaseConfidence: string;
  evaluatorVersion: string;
  evaluatedAt: string;
}