"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconSparkles,
  IconX,
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
  IconMessagePlus,
  IconDeviceFloppy,
  IconLayoutDashboard,
  IconArrowRight,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  aiActionsApi,
  type AiCardContext,
  type AiErrorDetails,
  type AskAndRunResult,
  type SuggestedSource,
} from "@/lib/api/ai-actions";
import {
  PROGRESS_STEPS,
  ProgressSteps,
  ResultChart,
  ResultTable,
} from "@/components/ai/ai-result-view";

export function AIQuestionResultModal({
  open,
  projectId,
  question,
  source,
  cardContext,
  onClose,
  onOpenAssistant,
  onCreateDashboard,
  notify,
}: {
  open: boolean;
  projectId: string;
  question: string;
  source?: string;
  cardContext?: AiCardContext;
  onClose: () => void;
  onOpenAssistant: (question: string) => void;
  onCreateDashboard?: (question: string) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const [showSql, setShowSql] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [saved, setSaved] = useState(false);

  const run = useMutation<AskAndRunResult, Error, string | undefined>({
    mutationFn: (chosenSource) =>
      aiActionsApi.askAndRun(
        projectId,
        question,
        chosenSource ?? source,
        cardContext,
      ),
  });

  const save = useMutation({
    mutationFn: (sql: string) =>
      aiActionsApi.saveQuery(
        projectId,
        question.replace(/\?+$/, "").slice(0, 120) || "AI Query",
        sql,
        question,
      ),
    onSuccess: (res) => {
      setSaved(true);
      notify(`Saved query "${res.name}"`, "success");
    },
    onError: (err: Error) => notify(err.message, "error"),
  });

  // Reset and kick off generation whenever the modal opens for a question.
  useEffect(() => {
    if (!open) return;
    setShowSql(false);
    setShowDetails(false);
    setSaved(false);
    setStepIndex(0);
    run.mutate(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, question]);

  // Animate the progress checklist while the single request is in flight.
  useEffect(() => {
    if (!open || !run.isPending) return;
    setStepIndex(0);
    const id = setInterval(() => {
      setStepIndex((i) => Math.min(i + 1, PROGRESS_STEPS.length - 1));
    }, 700);
    return () => clearInterval(id);
  }, [open, run.isPending]);

  const result = run.data;

  if (!open) return null;

  const needsClarification =
    result && result.status === "needs_clarification";
  const failedToGenerate =
    run.isError || (result && result.status === "generation_error");
  const executionError = result && result.status === "execution_error";
  const success = result && result.status === "success";
  const sql = result?.sql ?? "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4">
      <div className="my-8 w-full max-w-3xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconSparkles size={18} className="text-ai" />
              AI Answer
            </h2>
            <p className="mt-1 text-[13px] text-ink-secondary">{question}</p>
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

        <div className="mt-4">
          {run.isPending ? (
            <ProgressSteps activeIndex={stepIndex} />
          ) : needsClarification ? (
            <ClarificationBlock
              message={
                result?.message ||
                "I couldn't confidently identify which project source answers this question. Choose a source or rephrase the question."
              }
              sources={result?.suggestedSources ?? []}
              onPick={(name) => run.mutate(name)}
            />
          ) : failedToGenerate ? (
            <ErrorBlock
              title={
                run.isError
                  ? "We couldn't reach the AI service to answer this."
                  : result?.error ||
                    "We couldn't safely build a query for this question."
              }
              message={
                run.isError ? (run.error as Error).message : undefined
              }
              details={result?.errorDetails}
              showDetails={showDetails}
              onToggleDetails={() => setShowDetails((v) => !v)}
            />
          ) : (
            <>
              {executionError && (
                <ErrorBlock
                  title={
                    result?.error ||
                    "We couldn't run this query against the project's data."
                  }
                  details={result?.errorDetails}
                  showDetails={showDetails}
                  onToggleDetails={() => setShowDetails((v) => !v)}
                />
              )}

              {success && result?.explanation && (
                <p className="mb-3 text-[13px] text-ink-secondary">
                  {result.explanation}
                </p>
              )}

              {success && (
                <ResultChart
                  columns={result.columns}
                  rows={result.rows}
                  viz={result.suggestedVisualization}
                />
              )}

              {success && (
                <ResultTable
                  columns={result.columns}
                  rows={result.rows}
                />
              )}

              {sql && (
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={() => setShowSql((v) => !v)}
                    className="flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
                  >
                    {showSql ? (
                      <IconChevronDown size={14} />
                    ) : (
                      <IconChevronRight size={14} />
                    )}
                    {showSql ? "Hide SQL" : "Show SQL"}
                  </button>
                  {showSql && (
                    <pre className="mt-1.5 overflow-auto rounded-md bg-bg-secondary p-2.5 text-[11px] leading-relaxed text-ink-primary">
                      {sql}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-line-tertiary pt-4">
          {success && sql && (
            <>
              <Button
                variant="secondary"
                size="md"
                disabled={save.isPending || saved}
                onClick={() => save.mutate(sql)}
              >
                <IconDeviceFloppy size={15} />
                {saved ? "Saved" : save.isPending ? "Saving…" : "Save Query"}
              </Button>
              {onCreateDashboard && (
                <Button
                  variant="secondary"
                  size="md"
                  onClick={() => onCreateDashboard(question)}
                >
                  <IconLayoutDashboard size={15} />
                  Create Dashboard
                </Button>
              )}
              <Button
                variant="secondary"
                size="md"
                onClick={() => onOpenAssistant(question)}
              >
                <IconMessagePlus size={15} />
                Ask Follow-up
              </Button>
            </>
          )}
          {(failedToGenerate || executionError || needsClarification) && (
            <Button
              variant="secondary"
              size="md"
              onClick={() => onOpenAssistant(question)}
            >
              <IconArrowRight size={15} />
              Open in AI Assistant
            </Button>
          )}
          <Button variant="primary" size="md" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}

function ClarificationBlock({
  message,
  sources,
  onPick,
}: {
  message: string;
  sources: SuggestedSource[];
  onPick: (name: string) => void;
}) {
  return (
    <div className="rounded-md border border-line-tertiary bg-bg-secondary px-3 py-3 text-[13px] text-ink-primary">
      <div className="flex items-start gap-2">
        <IconSparkles size={16} className="mt-0.5 shrink-0 text-ai" />
        <div className="min-w-0">
          <div className="font-medium">{message}</div>
          {sources.length > 0 && (
            <div className="mt-2.5 flex flex-col gap-1.5">
              {sources.map((s) => (
                <button
                  key={s.name}
                  type="button"
                  onClick={() => onPick(s.name)}
                  className="flex items-center justify-between gap-3 rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-left hover:border-ai hover:bg-ai/5"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-ink-primary">
                      {s.name}
                    </span>
                    {s.reason && (
                      <span className="block truncate text-[12px] text-ink-tertiary">
                        {s.reason}
                      </span>
                    )}
                  </span>
                  <IconArrowRight
                    size={15}
                    className="shrink-0 text-ink-tertiary"
                  />
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ErrorBlock({
  title,
  message,
  details,
  showDetails,
  onToggleDetails,
}: {
  title: string;
  message?: string;
  details?: AiErrorDetails;
  showDetails: boolean;
  onToggleDetails: () => void;
}) {
  const rows: [string, string][] = [];
  if (details?.matchedSources?.length)
    rows.push(["Matched sources", details.matchedSources.join(", ")]);
  if (details?.validationError)
    rows.push(["Validation error", details.validationError]);
  if (details?.executionError)
    rows.push(["Execution error", details.executionError]);
  const hasTechnical = rows.length > 0 || Boolean(details?.sql);

  return (
    <div className="rounded-md border border-danger/30 bg-danger-bg px-3 py-2.5 text-[13px] text-danger">
      <div className="flex items-start gap-2">
        <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <div className="font-medium">{title}</div>
          {message && message !== title && (
            <div className="mt-0.5 text-ink-secondary">{message}</div>
          )}
        </div>
      </div>
      {hasTechnical && (
        <div className="mt-2">
          <button
            type="button"
            onClick={onToggleDetails}
            className="flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showDetails ? (
              <IconChevronDown size={14} />
            ) : (
              <IconChevronRight size={14} />
            )}
            {showDetails ? "Hide technical details" : "Show technical details"}
          </button>
          {showDetails && (
            <div className="mt-1.5 space-y-1.5">
              {rows.map(([label, value]) => (
                <div key={label} className="text-[12px] text-ink-secondary">
                  <span className="font-medium text-ink-primary">{label}:</span>{" "}
                  {value}
                </div>
              ))}
              {details?.sql && (
                <pre className="overflow-auto rounded-md bg-bg-secondary p-2.5 text-[11px] leading-relaxed text-ink-primary">
                  {details.sql}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
