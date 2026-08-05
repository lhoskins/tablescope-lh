"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ProjectResult } from "./project-result";
import { CrossProjectSynthesis } from "./cross-project-synthesis";
import { StreamProject } from "./stream-project";



// ── SSE events ───────────────────────────────────────────────────────────────

export type IntelligenceEvent =
  | { type: "start"; projects: StreamProject[] }
  | ({ type: "project_complete" } & ProjectResult)
  | {
      type: "project_error";
      error: string;
      projectId?: string;
      projectName?: string;
    }
  | { type: "synthesis_complete"; synthesis: CrossProjectSynthesis }
  | { type: "done"; projectCount: number };