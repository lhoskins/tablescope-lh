"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { IntelligenceEvent } from "./intelligence-event";



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