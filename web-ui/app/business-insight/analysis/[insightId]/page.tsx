"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  IconArrowLeft,
  IconChevronDown,
  IconFileText,
  IconLoader2,
  IconTable,
  IconTargetArrow,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import {
  InsightChartBlock,
  renderBold,
} from "@/components/tablescope/home/intelligence-card";
import { buildDiagnosticChart } from "@/lib/insights/diagnostic-chart";
import { InsightAskBox } from "@/components/tablescope/home/insight-ask-box";
import { insightReturnHref } from "@/lib/insights/return-target";
import {
  getIntelligenceSnapshot,
  suggestInsights,
  type InsightCard,
  type InsightDiagnostic,
  type ProjectResult,
} from "@/lib/api/home-intelligence";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "\u00b7\u00b7",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

/**
 * Deeper analysis for one insight — the shareable dissection of a finding.
 *
 * A card in the feed shows only the lead finding and the top proposed action;
 * this is where the whole line of reasoning lives: each diagnostic step with the
 * question it answers and why it was run, the actions those steps ground, other
 * sources worth checking, and the questions to ask next.
 *
 * The URL carries the insight id so the analysis can be sent to a colleague.
 */

const STAGE_LABELS: Record<string, string> = {
  localise: "Where it is concentrated",
  when: "When it changed",
  quantify: "How large it is",
  explain: "What explains it",
  project: "Where it is heading",
  corroborate: "Corroboration",
};

const ACTION_TONES: Record<string, string> = {
  mitigate: "border-danger/40 bg-danger/5",
  capture: "border-success/40 bg-success/5",
  investigate: "border-warning/40 bg-warning/5",
  monitor: "border-line-tertiary bg-bg-secondary",
};

function findCard(
  results: ProjectResult[] | undefined,
  insightId: string,
): InsightCard | null {
  for (const result of results ?? []) {
    for (const card of result.insights ?? []) {
      if ((card.insightId ?? card.id) === insightId) return card;
    }
  }
  return null;
}

/**
 * What the red marker means for this kind of step. A group comparison marks the
 * segment carrying the problem; a time-series step marks flagged observations.
 * One caption for both would be wrong in one of the two cases.
 */
function markerCaption(intent: string | undefined, count: number): string {
  if (intent === "compare_multiple_groups" || intent === "compare_two_groups") {
    return "The marked bar is the segment carrying the problem.";
  }
  if (intent === "detect_change_point") return "The marked point is where the level shifted.";
  return count === 1
    ? "The marked point is the flagged observation."
    : `The ${count} marked points are the flagged observations.`;
}

function DiagnosticStep({ step }: { step: InsightDiagnostic }) {
  const [showEvidence, setShowEvidence] = useState(false);
  // Presentation comes from the intent, not from this component. Hardcoding a
  // bar here ranked a 31-period series by magnitude and cut it to 25 points.
  const built = useMemo(() => buildDiagnosticChart(step), [step]);
  const rows = (step.result?.rows ?? []) as Record<string, unknown>[];
  const columns = step.result?.columns ?? [];

  return (
    <li className="rounded-xl border border-line-tertiary bg-bg-primary p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-ink-tertiary">
          {STAGE_LABELS[step.stage] ?? step.stage}
        </span>
        {step.highlight ? (
          <span className="rounded-full bg-brand-600/10 px-2 py-0.5 text-[12px] font-medium text-brand-600">
            {step.highlight}
          </span>
        ) : null}
        {step.crossReference ? (
          <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-[11px] text-ink-tertiary">
            cross-checked · {step.crossReference}
          </span>
        ) : step.triggeredBy ? (
          <span className="text-[11px] text-ink-tertiary">
            triggered: {step.triggeredBy}
          </span>
        ) : null}
      </div>

      <h3 className="mt-2 text-[15px] font-semibold text-ink-primary">{step.title}</h3>
      <p className="mt-0.5 text-[13px] text-ink-tertiary">{step.question}</p>
      <p className="mt-2 text-[14px] text-ink-secondary">{step.finding}</p>
      {/* Why this step was run — what turns a pile of charts into reasoning. */}
      <p className="mt-1 text-[12px] italic text-ink-tertiary">{step.rationale}</p>

      {built ? (
        <div className="mt-3">
          <InsightChartBlock chart={built.chart} options={built.options} />
          {built.anomalyRows.length > 0 ? (
            <p className="mt-1 text-[12px] text-ink-tertiary">
              <span className="mr-1 inline-block h-2 w-2 rounded-full bg-danger align-middle" />
              {markerCaption(step.intent, built.anomalyRows.length)}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {step.analyticalMethod?.method ? (
          <p className="text-[12px] text-ink-tertiary">
            Method: {step.analyticalMethod.method}
            {String(step.analyticalMethod.executionEngine ?? "").toLowerCase() === "r"
              ? " (R)"
              : ""}
            {step.analyticalMethod.usableN
              ? ` · ${step.analyticalMethod.usableN} observations`
              : ""}
          </p>
        ) : null}
        {rows.length > 0 ? (
          <button
            type="button"
            onClick={() => setShowEvidence((v) => !v)}
            aria-expanded={showEvidence}
            className="inline-flex items-center gap-1 text-[12px] font-medium text-brand-600 hover:underline"
          >
            {showEvidence ? "Hide" : `See all ${rows.length}`} observations
            <IconChevronDown
              size={13}
              className={showEvidence ? "rotate-180 transition-transform" : "transition-transform"}
              aria-hidden
            />
          </button>
        ) : null}
      </div>

      {showEvidence && rows.length > 0 ? (
        <EvidenceTable
          columns={columns}
          rows={rows}
          flagged={built?.anomalyRows ?? []}
        />
      ) : null}
    </li>
  );
}

/**
 * The observations a step was computed from.
 *
 * Rows the method flagged are marked here too — the chart shows *that* there is
 * an outlier, this shows *which* record it is, which is what someone has to
 * chase down to act on the finding.
 */
function EvidenceTable({
  columns,
  rows,
  flagged,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  flagged: number[];
}) {
  const flaggedSet = useMemo(() => new Set(flagged), [flagged]);
  return (
    <div className="mt-2 max-h-80 overflow-auto rounded-lg border border-line-tertiary">
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 bg-bg-secondary">
          <tr>
            <th className="border-b border-line-tertiary px-2 py-1.5 text-left font-medium text-ink-tertiary">
              #
            </th>
            {columns.map((c) => (
              <th
                key={c}
                className="border-b border-line-tertiary px-2 py-1.5 text-left font-medium text-ink-secondary"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const isFlagged = flaggedSet.has(i);
            return (
              <tr
                key={i}
                className={isFlagged ? "bg-danger/10" : undefined}
                title={isFlagged ? "Outside the expected range" : undefined}
              >
                <td className="px-2 py-1 text-ink-tertiary">
                  {isFlagged ? "!" : i + 1}
                </td>
                {columns.map((c) => (
                  <td
                    key={c}
                    className={`px-2 py-1 ${
                      isFlagged ? "font-medium text-ink-primary" : "text-ink-secondary"
                    }`}
                  >
                    {formatCell(row[c])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export default function InsightAnalysisPage() {
  const params = useParams<{ insightId: string }>();
  const insightId = decodeURIComponent(String(params?.insightId ?? ""));

  const { data: identity } = useCurrentUser();
  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  // A card can come from either surface: Business Insight reads the tenant-wide
  // snapshot, Project Insight its own per-project store. The id in the URL says
  // nothing about which one produced it, so resolve against both and take
  // whichever holds it — otherwise every Project-Insight link dead-ends here.
  const { data: snapshot, isLoading: snapshotLoading } = useQuery({
    queryKey: ["intelligence-snapshot"],
    queryFn: getIntelligenceSnapshot,
  });
  const businessCard = snapshot?.snapshot
    ? findCard(snapshot.snapshot.results, insightId)
    : null;

  // Only reached for ids the tenant snapshot does not hold.
  const { data: projectInsights, isLoading: projectLoading } = useQuery({
    queryKey: ["project-insights-for-analysis"],
    queryFn: () => suggestInsights(),
    enabled: !snapshotLoading && !businessCard,
  });

  const card = useMemo(
    () => businessCard ?? findCard(projectInsights?.projects, insightId),
    [businessCard, projectInsights, insightId],
  );
  const isLoading = snapshotLoading || (!businessCard && projectLoading);

  const diagnostics = card?.diagnostics ?? [];
  const actions = card?.proposedActions ?? [];
  const checked = new Set(
    diagnostics.map((d) => d.crossReference).filter(Boolean) as string[],
  );
  // A source that was actually tested is answered in the ladder above; listing
  // it again as an open question would re-ask a question already answered.
  const crossRefs = (card?.crossReferences ?? []).filter(
    (r) => !checked.has(r.name),
  );
  const questions = card?.suggestedQuestions ?? [];

  return (
    <AppShell mode="home" activeNav="business-insight" tenant={tenant} user={user}>
      <div className="mx-auto w-full max-w-content space-y-5 py-6">
        {/* Back to the CARD, not the top of a freshly-collapsed feed: the
            reader was mid-investigation and expects to carry on there. */}
        <Link
          href={insightReturnHref("/business-insight", insightId)}
          className="inline-flex items-center gap-1 text-[13px] text-ink-secondary hover:text-ink-primary"
        >
          <IconArrowLeft size={15} aria-hidden />
          Back to this insight
        </Link>

        {isLoading ? (
          <div className="flex items-center gap-2 text-small text-ink-tertiary">
            <IconLoader2 size={16} className="animate-spin" aria-hidden />
            Loading analysis…
          </div>
        ) : !card ? (
          <div className="rounded-xl border border-line-tertiary bg-bg-primary p-6">
            <h1 className="text-[17px] font-semibold text-ink-primary">
              Analysis not available
            </h1>
            <p className="mt-1 text-small text-ink-secondary">
              This insight is no longer in the current briefing — insights are
              regenerated when the underlying data changes. Open Business Insight
              to see the current findings.
            </p>
          </div>
        ) : (
          <>
            <header>
              <h1 className="text-[20px] font-semibold text-ink-primary">
                {renderBold(card.title)}
              </h1>
              {card.summary ? (
                <p className="mt-1 text-[14px] text-ink-secondary">
                  {renderBold(card.summary)}
                </p>
              ) : null}
            </header>

            {actions.length > 0 ? (
              <section aria-labelledby="proposed-actions">
                <h2
                  id="proposed-actions"
                  className="mb-2 text-[15px] font-semibold text-ink-primary"
                >
                  Proposed actions
                </h2>
                <ul className="space-y-2">
                  {actions.map((action, i) => (
                    <li
                      key={`${action.headline}-${i}`}
                      className={`rounded-lg border p-3 ${
                        ACTION_TONES[action.kind] ?? ACTION_TONES.monitor
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <IconTargetArrow
                          size={16}
                          className="mt-0.5 shrink-0 text-ink-secondary"
                          aria-hidden
                        />
                        <div>
                          <p className="text-[14px] font-medium text-ink-primary">
                            {action.headline}
                          </p>
                          <p className="mt-0.5 text-[13px] text-ink-secondary">
                            {action.rationale}
                          </p>
                          <p className="mt-1 text-[11px] uppercase tracking-wide text-ink-tertiary">
                            {action.kind} · {action.confidence} confidence
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section aria-labelledby="how-we-got-here">
              <h2
                id="how-we-got-here"
                className="mb-1 text-[15px] font-semibold text-ink-primary"
              >
                What we asked, and what the data answered
              </h2>
              <p className="mb-2 text-[13px] text-ink-tertiary">
                Each question below was run against the data — the answer is the
                finding, not a prompt to investigate yourself.
              </p>
              {diagnostics.length === 0 ? (
                <p className="text-[13px] text-ink-tertiary">
                  This insight has not been dissected yet.
                </p>
              ) : (
                <ol className="space-y-3">
                  {diagnostics.map((step, i) => (
                    <DiagnosticStep key={`${step.stage}-${i}`} step={step} />
                  ))}
                </ol>
              )}
            </section>

            {crossRefs.length > 0 ? (
              <section aria-labelledby="cross-references">
                <h2
                  id="cross-references"
                  className="mb-2 text-[15px] font-semibold text-ink-primary"
                >
                  Not yet checked
                </h2>
                <p className="mb-2 text-[13px] text-ink-tertiary">
                  Leads the analysis could not test automatically. Ask about any
                  of them below.
                </p>
                <ul className="space-y-2">
                  {crossRefs.map((ref, i) => (
                    <li
                      key={`${ref.name}-${i}`}
                      className="flex items-start gap-2 rounded-lg border border-line-tertiary bg-bg-primary p-3"
                    >
                      {ref.kind === "document" ? (
                        <IconFileText size={16} className="mt-0.5 shrink-0 text-ink-tertiary" aria-hidden />
                      ) : (
                        <IconTable size={16} className="mt-0.5 shrink-0 text-ink-tertiary" aria-hidden />
                      )}
                      <div>
                        <p className="text-[14px] text-ink-primary">{ref.question}</p>
                        <p className="mt-0.5 text-[12px] text-ink-tertiary">{ref.rationale}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {/* Cross-reference prompts are questions too, so they go into the
                same box rather than being a dead list. */}
            <InsightAskBox
              card={card}
              suggestions={[
                ...questions,
                ...crossRefs.map((r) => r.question).filter(Boolean),
              ]}
            />
          </>
        )}
      </div>
    </AppShell>
  );
}
