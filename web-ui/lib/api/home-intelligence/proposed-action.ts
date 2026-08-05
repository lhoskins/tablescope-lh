"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


/** A proposed next step grounded in the diagnostics. */
export interface ProposedAction {
  headline: string;
  rationale: string;
  /** mitigate | capture | investigate | monitor */
  kind: string;
  /** high | medium | low — low means the evidence did not isolate a cause. */
  confidence: string;
}