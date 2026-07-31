"use client";

import { useState } from "react";
import {
  IconX,
  IconInfoCircle,
  IconChevronRight,
  IconChevronDown,
  IconTable,
  IconFileText,
  IconDatabase,
  IconClock,
} from "@tabler/icons-react";
import { InsightAnalysisDetails } from "./insight-engine-badge";
import type { InsightCard, InsightExplanation } from "@/lib/api/home-intelligence";

interface InsightExplanationPanelProps {
  card: InsightCard;
  open: boolean;
  onClose: () => void;
  /** Whether this card is a frozen snapshot (e.g. a Home pin). */
  frozen?: boolean;
}

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

function Badge({ children, tone = "brand" }: { children: React.ReactNode; tone?: "brand" | "warning" | "success" | "info" }) {
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

function SqlBlock({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
        aria-expanded={open}
      >
        {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
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

function LegacyFallback({ card }: { card: InsightCard }) {
  return (
    <div className="rounded-md border border-line-tertiary bg-bg-secondary/50 p-4 text-[13px] text-ink-secondary">
      <p className="font-medium text-ink-primary">Explainability metadata unavailable</p>
      <p className="mt-1">
        This insight was generated before explainability details were added, or it
        came from a legacy pipeline. The summary and any available SQL are shown
        below.
      </p>
      {card.sql && <SqlBlock sql={card.sql} />}
    </div>
  );
}

function ExplanationContent({
  card,
  explanation,
}: {
  card: InsightCard;
  explanation: InsightExplanation;
}) {
  const confidenceTone =
    explanation.confidence.level === "high"
      ? "success"
      : explanation.confidence.level === "medium"
        ? "info"
        : "warning";

  return (
    <div className="space-y-4">
      <Section title="Summary">
        <p className="text-[13px] leading-relaxed text-ink-primary">
          {explanation.summary || card.summary}
        </p>
      </Section>

      <Section title="Method">
        <div className="flex items-center gap-2">
          <Badge tone={confidenceTone}>{explanation.methodLabel || explanation.method}</Badge>
          <span className="text-[12px] text-ink-tertiary">{explanation.method}</span>
        </div>
        {explanation.governance && (
          <div
            className={`mt-2 rounded-md p-2 text-[13px] ${
              explanation.governance.decision === "fallback"
                ? "bg-sky-50 text-sky-800"
                : explanation.governance.decision === "blocked"
                  ? "bg-rose-50 text-rose-800"
                  : "bg-emerald-50 text-emerald-800"
            }`}
          >
            <span className="font-medium">
              {explanation.governance.decision === "allowed"
                ? "Permitted"
                : explanation.governance.decision === "fallback"
                  ? "Fallback used"
                  : "Blocked"}
              :
            </span>{" "}
            {explanation.governance.message}
            <div className="mt-1 text-[11px] text-ink-tertiary">
              Requested {explanation.governance.requestedMethod} → effective{" "}
              {explanation.governance.effectiveMethod} (policy v
              {explanation.governance.policyVersion})
            </div>
          </div>
        )}
      </Section>

      <Section title="Steps">
        <ol className="list-decimal space-y-1 pl-4 text-[13px] text-ink-secondary">
          {explanation.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      </Section>

      <Section title="Source">
        <div className="space-y-1 text-[13px] text-ink-secondary">
          <div className="flex items-center gap-1">
            <IconDatabase size={13} className="text-ink-tertiary" />
            <span className="font-medium text-ink-primary">Project:</span>{" "}
            {explanation.source.projectName || card.projectName}
          </div>
          {explanation.source.dataSourceName && (
            <div className="flex items-center gap-1">
              <IconDatabase size={13} className="text-ink-tertiary" />
              <span className="font-medium text-ink-primary">Data source:</span>{" "}
              {explanation.source.dataSourceName}
            </div>
          )}
          {explanation.source.tables.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-ink-primary">Tables:</span>
              {explanation.source.tables.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 text-[12px] text-ink-tertiary">
                  <IconTable size={12} />
                  {t}
                </span>
              ))}
            </div>
          )}
          {explanation.source.fields.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="font-medium text-ink-primary">Fields:</span>
              {explanation.source.fields.map((f) => (
                <Badge key={f} tone="info">{f}</Badge>
              ))}
            </div>
          )}
        </div>
      </Section>

      {explanation.filters && explanation.filters.length > 0 && (
        <Section title="Filters">
          <ul className="space-y-1 text-[13px] text-ink-secondary">
            {explanation.filters.map((f, i) => (
              <li key={i}>
                <span className="font-medium text-ink-primary">{f.field}</span>{" "}
                {f.operator || "is"} <span className="font-medium">{String(f.value)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {explanation.metrics && explanation.metrics.length > 0 && (
        <Section title="Metrics">
          <ul className="space-y-1 text-[13px] text-ink-secondary">
            {explanation.metrics.map((m, i) => (
              <li key={i}>
                <span className="font-medium text-ink-primary">{m.name}</span>{" "}
                ({m.aggregation} of {m.field})
              </li>
            ))}
          </ul>
        </Section>
      )}

      {explanation.comparison && (
        <Section title="Comparison">
          <div className="grid grid-cols-2 gap-3 text-[13px]">
            <div className="rounded-md border border-line-tertiary bg-bg-secondary/40 p-2">
              <div className="text-[11px] uppercase tracking-wide text-ink-tertiary">Baseline</div>
              <div className="font-medium text-ink-primary">{explanation.comparison.baselineLabel}</div>
              <div className="text-ink-secondary">{explanation.comparison.baselineValue}</div>
            </div>
            <div className="rounded-md border border-line-tertiary bg-bg-secondary/40 p-2">
              <div className="text-[11px] uppercase tracking-wide text-ink-tertiary">Current</div>
              <div className="font-medium text-ink-primary">{explanation.comparison.currentLabel}</div>
              <div className="text-ink-secondary">{explanation.comparison.currentValue}</div>
            </div>
          </div>
        </Section>
      )}

      <Section title="Evidence">
        <div className="space-y-1 text-[13px] text-ink-secondary">
          <div>
            <span className="font-medium text-ink-primary">Rows evaluated:</span>{" "}
            {explanation.evidence.rowCount ?? "unknown"}
          </div>
          {explanation.evidence.resultColumns && explanation.evidence.resultColumns.length > 0 && (
            <div>
              <span className="font-medium text-ink-primary">Result columns:</span>{" "}
              {explanation.evidence.resultColumns.join(", ")}
            </div>
          )}
          {explanation.evidence.topFinding && (
            <div className="mt-1.5 rounded-md bg-bg-secondary/40 p-2 text-ink-primary">
              {explanation.evidence.topFinding}
            </div>
          )}
        </div>
      </Section>

      {explanation.sql && <SqlBlock sql={explanation.sql} />}

      {explanation.chart && (
        <Section title="Chart configuration">
          <div className="space-y-1 text-[13px] text-ink-secondary">
            <div>
              <span className="font-medium text-ink-primary">Type:</span> {explanation.chart.chartType}
            </div>
            {explanation.chart.labelColumn && (
              <div>
                <span className="font-medium text-ink-primary">Label:</span> {explanation.chart.labelColumn}
              </div>
            )}
            {explanation.chart.valueColumn && (
              <div>
                <span className="font-medium text-ink-primary">Value:</span> {explanation.chart.valueColumn}
              </div>
            )}
            {explanation.chart.valueColumn2 && (
              <div>
                <span className="font-medium text-ink-primary">Secondary value:</span> {explanation.chart.valueColumn2}
              </div>
            )}
          </div>
        </Section>
      )}

      <Section title="Assumptions">
        <ul className="list-disc space-y-1 pl-4 text-[13px] text-ink-secondary">
          {explanation.assumptions.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      </Section>

      <Section title="Limitations">
        <ul className="list-disc space-y-1 pl-4 text-[13px] text-ink-secondary">
          {explanation.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </Section>

      <Section title="Confidence">
        <div className="space-y-2 text-[13px] text-ink-secondary">
          {explanation.confidence.level && (
            <div className="flex items-center gap-2">
              <span className="font-medium text-ink-primary">Level:</span>{" "}
              <Badge tone={confidenceTone}>{explanation.confidence.level}</Badge>
              {typeof explanation.confidence.score === "number" && (
                <span className="text-ink-tertiary">({explanation.confidence.score.toFixed(2)})</span>
              )}
            </div>
          )}
          {explanation.confidence.basis && (
            <div>
              <span className="font-medium text-ink-primary">Basis:</span> {explanation.confidence.basis}
            </div>
          )}
          {card.confidenceEvaluation && card.confidenceEvaluation.factors.length > 0 && (
            <div className="space-y-1">
              <div className="font-medium text-ink-primary">Evidence factors</div>
              <ul className="space-y-1">
                {card.confidenceEvaluation.factors.map((factor, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className={
                      factor.status === "passed"
                        ? "text-success"
                        : factor.status === "failed"
                          ? "text-danger"
                          : "text-warning"
                    }>
                      {factor.status === "passed" ? "✓" : factor.status === "failed" ? "✗" : "~"}
                    </span>
                    <span className="text-ink-secondary">{factor.label} — {factor.evidence}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {card.confidenceEvaluation && card.confidenceEvaluation.caps.length > 0 && (
            <div>
              <span className="font-medium text-ink-primary">Confidence caps:</span>{" "}
              {card.confidenceEvaluation.caps.join(" ")}
            </div>
          )}
          {card.confidenceEvaluation && card.confidenceEvaluation.gaps.length > 0 && (
            <div className="rounded-md bg-warning/10 p-2 text-warning">
              <span className="font-medium">To raise confidence:</span>{" "}
              {card.confidenceEvaluation.gaps.join(" ")}
            </div>
          )}
        </div>
      </Section>

      <Section title="Generated">
        <div className="flex items-center gap-1 text-[12px] text-ink-tertiary">
          <IconClock size={13} />
          {explanation.generatedAt || card.executedAt}
        </div>
      </Section>
    </div>
  );
}

export function InsightExplanationPanel({
  card,
  open,
  onClose,
  frozen = false,
}: InsightExplanationPanelProps) {
  const [showRaw, setShowRaw] = useState(false);
  if (!open) return null;

  const explanation = card.explanation;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="insight-explanation-title"
    >
      <div
        className="my-8 w-full max-w-2xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2
              id="insight-explanation-title"
              className="flex items-center gap-2 text-h2 text-ink-primary"
            >
              <IconInfoCircle size={18} className="text-brand-500" />
              Explain insight
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              How this insight was produced, what data it used, and what it can
              and cannot tell you.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 text-ink-tertiary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </div>

        {frozen && (
          <div className="mb-4 rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-[12px] text-brand-700">
            This is a frozen snapshot. The explanation reflects the insight as
            it was captured, not the latest live data.
          </div>
        )}

        {explanation ? (
          <ExplanationContent card={card} explanation={explanation} />
        ) : (
          <LegacyFallback card={card} />
        )}

        <Section title="Analysis details">
          <InsightAnalysisDetails
            envelope={card.analyticalMethod}
            executedAt={card.executedAt}
          />
        </Section>

        <div className="mt-5 flex items-center justify-between border-t border-line-tertiary pt-4">
          <button
            type="button"
            onClick={() => setShowRaw((v) => !v)}
            className="text-[12px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showRaw ? "Hide raw card" : "Show raw card"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-brand-fg hover:bg-brand/90"
          >
            Close
          </button>
        </div>

        {showRaw && (
          <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-bg-secondary p-2.5 text-[10px] leading-relaxed text-ink-primary">
            {JSON.stringify(card, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
