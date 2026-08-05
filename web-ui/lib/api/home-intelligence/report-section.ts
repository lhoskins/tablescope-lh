"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


// ── Reports ──────────────────────────────────────────────────────────────────

export interface ReportSection {
  id: string;
  kind: "insight" | "text";
  /** For insight sections: the query definition to re-run on view. */
  insight?: {
    projectId: string;
    projectName: string;
    insightType: string;
    title: string;
  };
  /** For text sections. */
  text?: string;
}