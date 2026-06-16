"use client";

import { apiClient } from "@/lib/api-client";

// ── Insight card shape (mirrors the platform-api InsightCard dict) ───────────

export type InsightSeverity =
  | "critical"
  | "urgent"
  | "watch"
  | "opportunity"
  | "info";

export interface InsightChart {
  type: "bar" | "line" | "kpi_grid";
  title?: string;
  data: {
    series?: { label: string; value: number }[];
    threshold?: number;
    kpis?: { value: string; label: string; delta?: string }[];
  };
}

export interface InsightCallout {
  type: "risk" | "opportunity" | "info";
  text: string;
}

export interface InsightCard {
  id: string;
  projectId: string;
  projectName: string;
  projectColor: string;
  insightType: string;
  severity: InsightSeverity;
  title: string;
  summary: string;
  chart: InsightChart | null;
  callout: InsightCallout | null;
  sources: { tables: string[]; documents: string[] };
  executedAt: string;
}

export interface ProjectResult {
  projectId: string;
  projectName: string;
  projectColor: string;
  insights: InsightCard[];
}

export interface CrossProjectSynthesis {
  headline: string;
  body: string;
  projectIds: string[];
}

export interface StreamProject {
  id: string;
  name: string;
  color: string;
}

// ── SSE events ───────────────────────────────────────────────────────────────

export type IntelligenceEvent =
  | { type: "start"; projects: StreamProject[] }
  | ({ type: "project_complete" } & ProjectResult)
  | { type: "project_error"; error: string }
  | { type: "synthesis_complete"; synthesis: CrossProjectSynthesis }
  | { type: "done"; projectCount: number };

/**
 * Open the home-intelligence SSE stream and invoke `onEvent` for each event.
 * Returns an `AbortController` so the caller can cancel on unmount / refresh.
 */
export function streamHomeIntelligence(
  onEvent: (event: IntelligenceEvent) => void,
  options: { crossProject?: boolean; granularity?: number } = {},
): AbortController {
  const controller = new AbortController();
  const cross = options.crossProject ?? true;
  const granularity = options.granularity ?? 3;

  (async () => {
    let response: Response;
    try {
      response = await apiClient.stream(
        `/api/ai/home-intelligence/stream?cross_project=${cross}&granularity=${granularity}`,
        { signal: controller.signal },
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        onEvent({ type: "project_error", error: String(err) });
      }
      return;
    }

    if (!response.ok || !response.body) {
      onEvent({
        type: "project_error",
        error: `Stream failed: ${response.status}`,
      });
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const line = frame
            .split("\n")
            .find((l) => l.startsWith("data:"));
          if (!line) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            onEvent(JSON.parse(json) as IntelligenceEvent);
          } catch {
            /* ignore malformed frame */
          }
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        onEvent({ type: "project_error", error: String(err) });
      }
    }
  })();

  return controller;
}

// ── Saved snapshot (latest completed run) ────────────────────────────────────

export interface IntelligenceSnapshot {
  granularity: number;
  updatedAt: string | null;
  generatedAt?: string;
  projects: StreamProject[];
  results: ProjectResult[];
  synthesis: CrossProjectSynthesis | null;
}

export function getIntelligenceSnapshot(): Promise<{
  snapshot: IntelligenceSnapshot | null;
}> {
  return apiClient.get("/api/ai/home-intelligence/snapshot");
}

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

// ── Intelligence settings (user preferences) ─────────────────────────────────

export interface IntelligenceSettings {
  run_on_load: boolean;
  cross_project: boolean;
  email_digest: boolean;
  /** 1 = executive/high-level .. 5 = granular/detailed. */
  granularity: number;
}

export interface UserPreferences {
  intelligence: IntelligenceSettings;
}

export function getPreferences(): Promise<UserPreferences> {
  return apiClient.get("/api/users/preferences");
}

export function updatePreferences(
  intelligence: Partial<IntelligenceSettings>,
): Promise<UserPreferences> {
  return apiClient.patch("/api/users/preferences", { intelligence });
}

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

export interface ReportRecord {
  id: number;
  shareToken: string;
  shareUrl: string;
  title: string;
  sections: ReportSection[];
  shareSettings: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
}

export function createReport(body: {
  title: string;
  sections: ReportSection[];
  share_settings?: Record<string, unknown>;
}): Promise<ReportRecord> {
  return apiClient.post("/api/reports", body);
}

export function getReport(shareToken: string): Promise<ReportRecord> {
  return apiClient.get(`/api/reports/${shareToken}`);
}

export function listReports(): Promise<ReportRecord[]> {
  return apiClient.get("/api/reports");
}
