"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightExplanationConfidence } from "./insight-explanation-confidence";
import { InsightConfidenceFactor } from "./insight-confidence-factor";
import { InsightExplanationSource } from "./insight-explanation-source";
import { InsightExplanationMetric } from "./insight-explanation-metric";
import { InsightExplanationEvidence } from "./insight-explanation-evidence";
import { InsightExplanationChart } from "./insight-explanation-chart";
import { InsightExplanationFilter } from "./insight-explanation-filter";
import { InsightExplanationComparison } from "./insight-explanation-comparison";



export interface InsightExplanation {
  summary: string;
  method: string;
  methodLabel: string;
  steps: string[];
  source: InsightExplanationSource;
  filters?: InsightExplanationFilter[];
  metrics?: InsightExplanationMetric[];
  comparison?: InsightExplanationComparison;
  evidence: InsightExplanationEvidence;
  sql?: string;
  chart?: InsightExplanationChart;
  assumptions: string[];
  limitations: string[];
  confidence: InsightExplanationConfidence;
  confidenceFactors?: InsightConfidenceFactor[];
  confidenceCaps?: string[];
  confidenceGaps?: string[];
  whatWouldIncreaseConfidence?: string;
  generatedAt: string;
  governance?: {
    requestedMethod: string;
    effectiveMethod: string;
    decision: "allowed" | "fallback" | "blocked";
    policyVersion: number;
    message: string;
    evaluatedAt: string;
  };
}