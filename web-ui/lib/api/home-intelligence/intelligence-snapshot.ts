"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ProjectResult } from "./project-result";
import { CrossProjectSynthesis } from "./cross-project-synthesis";
import { StreamProject } from "./stream-project";



// ── Saved snapshot (latest completed run) ────────────────────────────────────

export interface IntelligenceSnapshot {
  granularity: number;
  updatedAt: string | null;
  generatedAt?: string;
  projects: StreamProject[];
  results: ProjectResult[];
  synthesis: CrossProjectSynthesis | null;
  /** True when the Knowledge Graph for one or more projects rebuilt after this briefing. */
  stale?: boolean;
  /** Project IDs whose data changed after this briefing was generated. */
  staleProjects?: string[];
  /** The run_id of an in-progress Business Insight analysis, if any. */
  activeRunId?: string | null;
  /** True when the active run has finished (snapshot is the final result). */
  activeRunComplete?: boolean | null;
}