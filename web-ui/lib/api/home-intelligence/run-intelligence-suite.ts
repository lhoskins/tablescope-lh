"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ProjectResult } from "./project-result";



// ── Single-project re-run (report viewer) ────────────────────────────────────

export function runIntelligenceSuite(
  projectId: number,
  promptTypes?: string[],
  granularity = 3,
): Promise<ProjectResult & { error?: string }> {
  return apiClient.post("/api/ai/run-intelligence-suite", {
    project_id: projectId,
    prompt_types: promptTypes,
    granularity,
  });
}