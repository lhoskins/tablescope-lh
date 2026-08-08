"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface EvidenceFingerprint {
  fingerprintVersion: number;
  planFingerprint: string | null;
  resultFingerprint: string | null;
  semanticFingerprint: string | null;
  seriesFingerprint: string | null;
  tenant_id?: number;
}