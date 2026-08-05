"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface InsightExplanationEvidence {
  rowCount: number | null;
  resultColumns: string[] | null;
  topFinding?: string | null;
}