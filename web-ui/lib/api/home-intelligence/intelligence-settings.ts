"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


// ── Intelligence settings (user preferences) ─────────────────────────────────

export interface IntelligenceSettings {
  run_on_load: boolean;
  cross_project: boolean;
  email_digest: boolean;
  /** 1 = executive/high-level .. 5 = granular/detailed. */
  granularity: number;
  /** Decisions, risks, KPIs, and questions the user wants prioritized on Home. */
  home_focus: string[];
}
