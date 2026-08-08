"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { VizDecision } from "./viz-decision";



export interface VizCandidate {
  decision: VizDecision;
  score: number;
  supported: boolean;
  unsupportedReason?: string;
}