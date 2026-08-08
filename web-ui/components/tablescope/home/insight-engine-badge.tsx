"use client";

import { IconInfoCircle } from "@tabler/icons-react";
import { MethodEnvelopeBlock } from "@/components/ai/method-envelope";
import type { MethodEnvelope } from "@/lib/api/ai-actions";

export interface EngineDisplay {
  engine: string | null;
  fallbackFrom: string | null;
  methodName: string | null;
  methodId: string | null;
  status: string | null;
  quality: string | null;
  label: string;
}

export function getInsightEngineDisplay(
  envelope?: MethodEnvelope | null,
): EngineDisplay {
  const engine = (envelope?.executionEngine ?? null)?.toLowerCase() ?? null;
  const fallbackFrom = (envelope?.fallbackFrom ?? null)?.toLowerCase() ?? null;
  const methodName = envelope?.methodName ?? null;
  const methodId = envelope?.method ?? null;
  const status = envelope?.status ?? null;
  const quality = envelope?.quality ?? null;

  let label = engine ? (engine === "r" ? "R Analytics" : "Python") : "Unknown";
  if (fallbackFrom) {
    label = `${engine ?? "Python"} fallback`;
  }

  return { engine, fallbackFrom, methodName, methodId, status, quality, label };
}

export function shouldShowRAnalyticsBadge(
  envelope?: MethodEnvelope | null,
): boolean {
  if (!envelope) return false;
  const { engine } = getInsightEngineDisplay(envelope);
  return (
    engine === "r" &&
    envelope.status === "ok" &&
    !envelope.fallbackFrom
  );
}

export function RAnalyticsBadge({
  envelope,
}: {
  envelope?: MethodEnvelope | null;
}) {
  if (!shouldShowRAnalyticsBadge(envelope)) return null;
  return (
    <span
      className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700"
      title="This insight includes analysis executed with R."
      aria-label="This insight includes analysis executed with R."
    >
      R Analytics
    </span>
  );
}

export function InsightAnalysisDetails({
  envelope,
  executedAt,
}: {
  envelope?: MethodEnvelope | null;
  executedAt?: string | null;
}) {
  if (!envelope) {
    return (
      <div className="rounded-md border border-line-tertiary bg-bg-secondary/50 p-3 text-[12px] text-ink-secondary">
        <p className="font-medium text-ink-primary">Provenance not available</p>
        <p className="mt-0.5">
          This insight was generated before analytical-method provenance was
          added, or it came from a pipeline that does not run the method engine.
        </p>
      </div>
    );
  }

  return (
    <details className="group rounded-md border border-line-tertiary bg-bg-secondary/50 p-3">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12px] font-medium text-ink-primary">
        <IconInfoCircle size={13} className="text-ink-tertiary" />
        Analysis details
        <span className="ml-auto text-ink-tertiary transition group-open:rotate-180">
          ▼
        </span>
      </summary>
      <div className="mt-2">
        <MethodEnvelopeBlock envelope={envelope} executedAt={executedAt} />
      </div>
    </details>
  );
}
