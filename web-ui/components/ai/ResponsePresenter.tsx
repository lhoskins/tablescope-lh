"use client";

import { useState } from "react";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { ResultChart, ResultTable } from "@/components/ai/ai-result-view";
import type { ResponseEnvelope } from "@/lib/api/ai-actions";

/**
 * Shared renderer for the unified {@link ResponseEnvelope} (M4 fast-follow).
 *
 * The one section-per-mode registry decides *which* sections appear and in what
 * order (`envelope.sections`); this component maps each section name to its
 * renderable piece. Surfaces converge on this instead of each sniffing a
 * bespoke response schema. Action affordances (save_query, create_dashboard,
 * follow_ups) are intentionally left to each surface's footer.
 */

const CONTENT_SECTIONS = new Set([
  "summary",
  "executive_summary",
  "prose_answer",
  "key_points",
  "key_drivers",
  "recommended_actions",
  "chart",
  "grid",
  "show_sql",
  "method_envelope",
  "sources",
  "references",
]);

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

function Prose({ text, muted }: { text: string; muted?: boolean }) {
  return (
    <p
      className={
        muted
          ? "mb-3 text-[13px] text-ink-secondary"
          : "whitespace-pre-wrap text-[13px] leading-relaxed text-ink-primary"
      }
    >
      {text}
    </p>
  );
}

function BulletList({ title, items }: { title: string; items: unknown[] }) {
  const rendered = items.map(asText).filter(Boolean);
  if (!rendered.length) return null;
  return (
    <div className="mb-3">
      <div className="mb-1 text-[12px] font-medium text-ink-secondary">
        {title}
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink-primary">
        {rendered.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

function MethodEnvelopeBlock({
  envelope,
}: {
  envelope: NonNullable<ResponseEnvelope["method_envelope"]>;
}) {
  const name = envelope.methodName ?? envelope.method;
  if (!name) return null;
  const caveats = (envelope.caveats ?? []).map(asText).filter(Boolean);
  return (
    <div className="mb-3 rounded-md border border-line-tertiary bg-bg-secondary px-3 py-2 text-[12px]">
      <div className="font-medium text-ink-primary">
        Analytical method: {name}
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-ink-tertiary">
        {envelope.tier != null && <span>Tier {envelope.tier}</span>}
        {envelope.n != null && <span>n = {envelope.n}</span>}
        {envelope.quality && <span>Quality: {envelope.quality}</span>}
      </div>
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

function ShowSql({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
      >
        {open ? (
          <IconChevronDown size={14} />
        ) : (
          <IconChevronRight size={14} />
        )}
        {open ? "Hide SQL" : "Show SQL"}
      </button>
      {open && (
        <pre className="mt-1.5 overflow-auto rounded-md bg-bg-secondary p-2.5 text-[11px] leading-relaxed text-ink-primary">
          {sql}
        </pre>
      )}
    </div>
  );
}

export function ResponsePresenter({
  envelope,
}: {
  envelope: ResponseEnvelope;
}) {
  const sections = envelope.sections.filter((s) => CONTENT_SECTIONS.has(s));
  const columns = envelope.columns ?? [];
  const rows = envelope.rows ?? [];

  const renderSection = (section: string) => {
    switch (section) {
      case "summary":
        return envelope.summary ? (
          <Prose muted text={envelope.summary} />
        ) : null;
      case "executive_summary":
        return envelope.executive_summary ? (
          <Prose muted text={envelope.executive_summary} />
        ) : null;
      case "prose_answer":
        return envelope.answer ? <Prose text={envelope.answer} /> : null;
      case "key_points":
        return envelope.key_points ? (
          <BulletList title="Key points" items={envelope.key_points} />
        ) : null;
      case "key_drivers":
        return envelope.key_drivers ? (
          <BulletList title="Key drivers" items={envelope.key_drivers} />
        ) : null;
      case "recommended_actions":
        return envelope.recommended_actions ? (
          <BulletList
            title="Recommended actions"
            items={envelope.recommended_actions}
          />
        ) : null;
      case "chart":
        return envelope.chart ? (
          <ResultChart columns={columns} rows={rows} viz={envelope.chart} />
        ) : null;
      case "grid":
        return rows.length || columns.length ? (
          <ResultTable columns={columns} rows={rows} />
        ) : null;
      case "show_sql":
        return envelope.sql ? <ShowSql sql={envelope.sql} /> : null;
      case "method_envelope":
        return envelope.method_envelope ? (
          <MethodEnvelopeBlock envelope={envelope.method_envelope} />
        ) : null;
      case "sources":
        return envelope.sources ? (
          <BulletList title="Sources" items={envelope.sources} />
        ) : null;
      case "references":
        return envelope.references ? (
          <BulletList title="References" items={envelope.references} />
        ) : null;
      default:
        return null;
    }
  };

  return (
    <div data-testid="response-presenter" data-mode={envelope.mode}>
      {sections.map((section) => {
        const node = renderSection(section);
        return node ? <div key={section}>{node}</div> : null;
      })}
    </div>
  );
}
