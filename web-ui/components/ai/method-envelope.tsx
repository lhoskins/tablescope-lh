"use client";

import type { MethodEnvelope } from "@/lib/api/ai-actions";

function asText(item: unknown): string {
  if (item == null) return "";
  if (typeof item === "string") return item;
  if (typeof item === "number" || typeof item === "boolean") return String(item);
  if (typeof item === "object") {
    const o = item as Record<string, unknown>;
    for (const key of ["label", "name", "title", "driver", "action", "text"]) {
      if (typeof o[key] === "string") return o[key] as string;
    }
    return JSON.stringify(item);
  }
  return String(item);
}

export function MethodEnvelopeBlock({
  envelope,
}: {
  envelope: MethodEnvelope;
}) {
  const name = envelope.methodName ?? envelope.method;
  if (!name) return null;
  const caveats = (envelope.caveats ?? []).map(asText).filter(Boolean);
  const assumptions = (envelope.assumptions ?? []).map(asText).filter(Boolean);
  const warnings = (envelope.warnings ?? []).map(asText).filter(Boolean);
  const results = envelope.results ?? null;
  const resultEntries = results
    ? Object.entries(results).filter(([, v]) => v != null && typeof v !== "object")
    : [];
  return (
    <div className="mb-3 rounded-md border border-line-tertiary bg-bg-secondary px-3 py-2 text-[12px]">
      <div className="font-medium text-ink-primary">
        Analytical method: {name}
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-ink-tertiary">
        {envelope.tier != null && <span>Tier {envelope.tier}</span>}
        {envelope.n != null && <span>n = {envelope.n}</span>}
        {envelope.usableN != null && <span>usable n = {envelope.usableN}</span>}
        {envelope.quality && <span>Quality: {envelope.quality}</span>}
      </div>
      {resultEntries.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-ink-secondary">
          {resultEntries.map(([k, v]) => (
            <span key={k}>
              {k}: {String(v)}
            </span>
          ))}
        </div>
      )}
      {assumptions.length > 0 && (
        <div className="mt-1 text-ink-tertiary">
          Assumptions: {assumptions.join("; ")}
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-700">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
      {caveats.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-secondary">
          {caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
