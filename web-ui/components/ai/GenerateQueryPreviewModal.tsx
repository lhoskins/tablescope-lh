"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconSparkles,
  IconX,
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
  IconDeviceFloppy,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  aiActionsApi,
  type GenerateQueryPreviewResult,
} from "@/lib/api/ai-actions";
import {
  PROGRESS_STEPS,
  ProgressSteps,
  ResultChart,
  ResultTable,
} from "@/components/ai/ai-result-view";

/**
 * Generate + execute a recommended query and preview it before saving.
 *
 * Reuses the shared result view (chart + table) and the generate-query-preview
 * endpoint. Save persists via the existing AI save-query action.
 */
export function GenerateQueryPreviewModal({
  open,
  projectId,
  question,
  title,
  description,
  onClose,
  onSaved,
  notify,
}: {
  open: boolean;
  projectId: string;
  question: string;
  title?: string;
  description?: string;
  onClose: () => void;
  onSaved?: (queryId: number) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const [showSql, setShowSql] = useState(false);
  const [saved, setSaved] = useState(false);

  const run = useMutation<GenerateQueryPreviewResult>({
    mutationFn: () =>
      aiActionsApi.generateQueryPreview(
        projectId,
        question,
        title,
        description,
      ),
  });

  const save = useMutation({
    mutationFn: (result: GenerateQueryPreviewResult) =>
      aiActionsApi.saveQuery(
        projectId,
        result.title || question.slice(0, 120) || "AI Query",
        result.sql,
        result.description || question,
      ),
    onSuccess: (res) => {
      setSaved(true);
      notify(`Saved query "${res.name}"`, "success");
      onSaved?.(res.query_id);
    },
    onError: (err: Error) => notify(err.message, "error"),
  });

  useEffect(() => {
    if (!open) return;
    setShowSql(false);
    setSaved(false);
    setStepIndex(0);
    run.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, question, title]);

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

  const failedToGenerate =
    run.isError || (result && result.status === "generation_error");
  const executionError = result && result.status === "execution_error";
  const success = result && result.status === "success";
  const sql = result?.sql ?? "";
  const headerTitle = result?.title || title || "Generated Query";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4">
      <div className="my-8 w-full max-w-3xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconSparkles size={18} className="text-ai" />
              {headerTitle}
            </h2>
            {(result?.description || description || question) && (
              <p className="mt-1 text-[13px] text-ink-secondary">
                {result?.description || description || question}
              </p>
            )}
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
          ) : failedToGenerate ? (
            <div className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-bg px-3 py-2.5 text-[13px] text-danger">
              <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-medium">
                  Couldn&apos;t generate this query.
                </div>
                <div className="mt-0.5 text-ink-secondary">
                  {run.isError ? (run.error as Error).message : result?.error}
                </div>
              </div>
            </div>
          ) : (
            <>
              {executionError && (
                <div className="mb-3 flex items-start gap-2 rounded-md border border-danger/30 bg-danger-bg px-3 py-2.5 text-[13px] text-danger">
                  <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
                  <div>
                    <div className="font-medium">
                      The query could not be executed.
                    </div>
                    <div className="mt-0.5 text-ink-secondary">
                      {result?.error}
                    </div>
                  </div>
                </div>
              )}

              {success && (
                <ResultChart
                  columns={result.columns}
                  rows={result.rows}
                  viz={result.suggestedVisualization}
                />
              )}
              {success && (
                <ResultTable columns={result.columns} rows={result.rows} />
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
            <Button
              variant="secondary"
              size="md"
              disabled={save.isPending || saved}
              onClick={() => save.mutate(result)}
            >
              <IconDeviceFloppy size={15} />
              {saved ? "Saved" : save.isPending ? "Saving…" : "Save Query"}
            </Button>
          )}
          <Button variant="primary" size="md" onClick={onClose}>
            {saved ? "Done" : "Discard"}
          </Button>
        </div>
      </div>
    </div>
  );
}
