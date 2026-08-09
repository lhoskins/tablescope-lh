"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { IconSparkles } from "@tabler/icons-react";
import { ResultChart, ResultTable } from "@/components/ai/ai-result-view";
import { MatchedInsightBlock } from "@/components/tablescope/conversation/matched-insight-block";
import { RAnalyticsBadge } from "./insight-engine-badge";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
import { aiActionsApi, type AiCardContext, type AskAndRunResult } from "@/lib/api/ai-actions";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import type { InsightCard, InsightDiagnostic } from "@/lib/api/home-intelligence";

/**
 * Ask anything about one insight.
 *
 * The suggested questions are a starting point, not the menu — a reader who
 * wants to cross-reference a supplier list or ask something nobody anticipated
 * types it here. Every question carries the card with it (its text, its method
 * and the query it was computed from), so the answer extends the rows behind
 * the finding rather than being generated against the project at large.
 */
export function InsightAskBox({
  card,
  suggestions,
}: {
  card: InsightCard;
  suggestions: string[];
}) {
  const { data: identity } = useCurrentUser();
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");

  const ask = useMutation<AskAndRunResult, Error, string>({
    mutationFn: (q) =>
      aiActionsApi.askAndRun(card.projectId, q, "insight-analysis", cardContext(card)),
  });

  const submit = (q: string) => {
    const trimmed = q.trim();
    if (!trimmed || ask.isPending) return;
    setAsked(trimmed);
    ask.mutate(trimmed);
  };

  const result = ask.data;
  const failed =
    result?.status === "generation_error" ||
    result?.status === "execution_error" ||
    Boolean(result?.error);

  return (
    <section aria-labelledby="ask-about-insight" className="space-y-3">
      <h2 id="ask-about-insight" className="text-[15px] font-semibold text-ink-primary">
        Ask about this insight
      </h2>

      {suggestions.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {suggestions.map((q) => (
            <li key={q}>
              <button
                type="button"
                onClick={() => {
                  setQuestion(q);
                  submit(q);
                }}
                disabled={ask.isPending}
                className="inline-flex items-center gap-1 rounded-full border border-line-tertiary px-3 py-1.5 text-[13px] text-ink-secondary transition-colors hover:bg-bg-secondary hover:text-ink-primary disabled:opacity-50"
              >
                <IconSparkles size={13} aria-hidden />
                {q}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <AskAnythingComposer
        value={question}
        onChange={setQuestion}
        onSubmit={submit}
        placeholder="Ask your own question about this insight…"
        ariaLabel="Ask your own question about this insight"
        submitAriaLabel="Ask"
        busy={ask.isPending}
        voiceEnabled={identity?.tenant.voiceInputEnabled ?? false}
        projectId={card.projectId}
      />

      {ask.isPending ? (
        <p className="text-[13px] text-ink-tertiary">Analysing “{asked}”…</p>
      ) : null}

      {ask.isError ? (
        <p className="text-[13px] text-danger">
          That question could not be answered right now. Try rephrasing it.
        </p>
      ) : null}

      {result ? (
        <div className="rounded-xl border border-line-tertiary bg-bg-primary p-4">
          <p className="text-[13px] font-medium text-ink-primary">{asked}</p>

          {failed ? (
            <p className="mt-2 text-[13px] text-danger">
              {result.message || result.error || "No answer could be produced."}
            </p>
          ) : (
            <>
              {result.explanation ? (
                <p className="mt-2 whitespace-pre-wrap text-[14px] text-ink-secondary">
                  {result.explanation}
                </p>
              ) : null}

              {result.analyticalMethod ? (
                <div className="mt-2">
                  <RAnalyticsBadge envelope={result.analyticalMethod} />
                </div>
              ) : null}

              {result.matchedInsight ? (
                <MatchedInsightBlock match={result.matchedInsight} />
              ) : result.rows?.length ? (
                /* Charts and tables use the same fit-ranked path as the cards. */
                <>
                  <div className="mt-3">
                    <ResultChart
                      columns={result.columns}
                      rows={result.rows}
                      viz={result.suggestedVisualization}
                    />
                  </div>
                  <div className="mt-3">
                    <ResultTable columns={result.columns} rows={result.rows} />
                  </div>
                </>
              ) : result.answerType === "data" ? (
                <p className="mt-2 text-[13px] text-ink-tertiary">
                  That query returned no rows.
                </p>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

/**
 * What the card knows about itself, sent so the backend can ground the answer.
 *
 * The SQL is the important part: it is what lets a follow-up extend the exact
 * rows the finding was computed from. Preferring a diagnostic's query over the
 * card's keeps a question asked beside a specific step tied to that step.
 */
export function cardContext(card: InsightCard): AiCardContext {
  const step: InsightDiagnostic | undefined = card.diagnostics?.[0];
  return {
    insight_type: card.insightType,
    source_tables: card.sources?.tables ?? [],
    metric: card.valueColumn ?? undefined,
    title: card.title,
    summary: card.summary,
    base_sql: card.sql || step?.sql || undefined,
    analytical_method: card.analyticalMethod ?? step?.analyticalMethod,
  };
}
