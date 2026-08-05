"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


/** Another source worth checking the finding against. */
export interface CrossReference {
  /** table | document */
  kind: string;
  name: string;
  question: string;
  rationale: string;
}