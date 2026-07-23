"use client";

import { useState } from "react";
import { IconChevronRight, IconChevronDown, IconTable } from "@tabler/icons-react";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { InsightAnalysisDetails } from "./insight-engine-badge";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line-tertiary pt-4 first:border-t-0 first:pt-0">
      <h4 className="mb-2 text-[12px] font-bold uppercase tracking-wide text-ink-tertiary">
        {title}
      </h4>
      {children}
    </section>
  );
}

function Badge({
  children,
  tone = "brand",
}: {
  children: React.ReactNode;
  tone?: "brand" | "warning" | "success" | "info";
}) {
  const toneClass =
    tone === "warning"
      ? "bg-warning/10 text-warning"
      : tone === "success"
        ? "bg-success/10 text-success"
        : tone === "info"
          ? "bg-brand-50 text-brand-700"
          : "bg-brand-50 text-brand-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${toneClass}`}>
      {children}
    </span>
  );
}

function EvidenceBadge({ status }: { status?: string }) {
  if (!status) return null;
  const tone =
    status === "supported"
      ? "success"
      : status === "partially_supported"
        ? "info"
        : status === "conflicting"
          ? "warning"
          : "warning";
  const label = status.replace(/_/g, " ");
  return <Badge tone={tone}>{label}</Badge>;
}

export function MultiEntityInsightCollapsed({ card }: { card: InsightCard }) {
  const entities = card.entities || [];
  const primaryMetric = entities[0]?.metrics?.[0];
  return (
    <div className="mt-3 space-y-3">
      <p className="text-body text-ink-secondary">{card.summary}</p>

      <div className="flex flex-wrap gap-2">
        {entities.map((e) => (
          <div
            key={String(e.id)}
            className="rounded-md border border-line-tertiary bg-bg-secondary px-3 py-2"
          >
            <div className="text-small font-medium text-ink-primary">{e.name}</div>
            {primaryMetric && (
              <div className="text-small text-ink-tertiary">
                {e.metrics?.[0]?.formattedValue ?? "—"} {e.metrics?.[0]?.label}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <EvidenceBadge status={card.evidenceStatus} />
        {card.entityType && <Badge tone="info">{card.entityType}</Badge>}
      </div>
    </div>
  );
}

export function MultiEntityInsightExplain({ card }: { card: InsightCard }) {
  const [showSql, setShowSql] = useState(false);
  const [showJoins, setShowJoins] = useState(false);
  const entities = card.entities || [];
  const lineage = card.lineage as any;
  const analysis = card.analysis;
  const strategy = lineage?.sourceStrategy;
  const joins = lineage?.joins || [];
  const sources = lineage?.sources || [];
  const warnings = (lineage?.validation?.warnings || []).concat(card.warnings || []);

  return (
    <div className="space-y-4 text-[13px] text-ink-secondary">
      <Section title="What we found">
        <p>{card.summary}</p>
        <div className="mt-2 flex items-center gap-2">
          <EvidenceBadge status={card.evidenceStatus} />
          {strategy?.fallbackUsed && (
            <Badge tone="warning">Single-source fallback</Badge>
          )}
        </div>
      </Section>

      <Section title="Entity comparison">
        <div className="overflow-auto">
          <table className="min-w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-line-tertiary text-ink-tertiary">
                <th className="py-1 pr-3 font-medium">Entity</th>
                {(entities[0]?.metrics || []).map((m) => (
                  <th key={m.key} className="py-1 pr-3 font-medium">
                    {m.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entities.map((e) => (
                <tr key={String(e.id)} className="border-b border-line-tertiary/50">
                  <td className="py-1.5 pr-3 font-medium text-ink-primary">{e.name}</td>
                  {e.metrics.map((m) => (
                    <td key={m.key} className="py-1.5 pr-3">
                      {m.formattedValue}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Primary analysis">
        {analysis?.primary ? (
          <InsightAnalysisDetails envelope={analysis.primary} />
        ) : (
          <p className="text-ink-tertiary">No primary method envelope available.</p>
        )}
      </Section>

      {analysis?.supporting && analysis.supporting.length > 0 && (
        <Section title="Supporting evidence">
          <div className="space-y-2">
            {analysis.supporting.map((env, i) => (
              <InsightAnalysisDetails key={i} envelope={env} />
            ))}
          </div>
        </Section>
      )}

      <Section title="Sources and joins">
        <div className="flex flex-wrap gap-2">
          {sources.map((s: any) => (
            <span key={s.tableId} className="inline-flex items-center gap-1 rounded-md bg-bg-secondary px-2 py-1 text-[12px]">
              <IconTable size={13} /> {s.displayName || s.tableId}
            </span>
          ))}
        </div>
        {joins.length > 0 && (
          <button
            type="button"
            onClick={() => setShowJoins((v) => !v)}
            className="mt-2 flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showJoins ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            {showJoins ? "Hide join lineage" : "Show join lineage"}
          </button>
        )}
        {showJoins && (
          <div className="mt-2 space-y-2">
            {joins.map((j: any, i: number) => (
              <div key={i} className="rounded-md bg-bg-secondary p-2 text-[12px]">
                <div className="font-medium text-ink-primary">
                  {j.left} ↔ {j.right}
                </div>
                <div className="text-ink-tertiary">
                  Declared: {j.declared_cardinality}; Observed: {j.observed_cardinality || "unknown"};{" "}
                  Fan-out: {j.fanout_ratio?.toFixed(2) ?? "n/a"}; Status: {j.validation_status}
                </div>
              </div>
            ))}
          </div>
        )}
        {strategy?.fallbackUsed && (
          <p className="mt-2 text-[12px] text-ink-tertiary">
            Single-source fallback: {strategy.fallbackReason}
          </p>
        )}
      </Section>

      <Section title="Data scope">
        <ul className="list-inside list-disc space-y-1">
          <li>Entity type: {card.entityType || "unknown"}</li>
          <li>Resolved entities: {entities.map((e) => e.name).join(", ") || "none"}</li>
          <li>Sources used: {strategy?.selectedSourceCount ?? sources.length}</li>
          <li>Strategy: {strategy?.preference || "unknown"}</li>
        </ul>
      </Section>

      {warnings.length > 0 && (
        <Section title="Data-quality warnings">
          <ul className="list-inside list-disc space-y-1 text-warning">
            {warnings.map((w: string, i: number) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Technical details">
        {lineage?.queryHash && (
          <div className="text-[12px] text-ink-tertiary">Query hash: {lineage.queryHash}</div>
        )}
        {card.sql && (
          <>
            <button
              type="button"
              onClick={() => setShowSql((v) => !v)}
              className="mt-2 flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
            >
              {showSql ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
              {showSql ? "Hide SQL" : "Show SQL"}
            </button>
            {showSql && (
              <pre className="mt-1.5 overflow-auto rounded-md bg-bg-secondary p-2.5 text-[11px] leading-relaxed text-ink-primary">
                {card.sql}
              </pre>
            )}
          </>
        )}
      </Section>
    </div>
  );
}
