"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


// ── Intelligence settings (user preferences) ─────────────────────────────────

export type HomePersona =
  | "ceo"
  | "cfo"
  | "cio"
  | "cdo"
  | "executive"
  | "it_manager"
  | "it_director"
  | "manufacturing_director"
  | "business_analyst"
  | "engineer";

export interface IntelligenceSettings {
  run_on_load: boolean;
  cross_project: boolean;
  email_digest: boolean;
  /** 1 = executive/high-level .. 5 = granular/detailed. */
  granularity: number;
  /** Decisions, risks, KPIs, and questions the user wants prioritized on Home. */
  home_focus: string[];
  /** Role-based analytical lens for Home. This is not an authorization role. */
  home_persona: HomePersona;
}
