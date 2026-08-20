"use client";

import { useEffect, useMemo, useState } from "react";
import { IconSparkles, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { GenerateQueryPreviewModal } from "@/components/ai/GenerateQueryPreviewModal";

const PERIODS = [
  ["30_days", "30 days"],
  ["60_days", "60 days"],
  ["90_days", "90 days"],
  ["6_months", "6 months"],
  ["1_year", "1 year"],
  ["2_years", "2 years"],
] as const;

/**
 * Turns an enumerated list of specific columns/metrics into an explicit
 * instruction prepended to the free-text prompt -- the same pattern the AI
 * Dashboard Designer uses for "Specific charts" (buildDesignPrompt in
 * ai-dashboard-designer.tsx), adapted for a single query result set instead
 * of multiple widgets. generate-query-preview's API only takes a free-text
 * question, so period/dimension are folded into that same string rather
 * than sent as separate structured fields.
 */
function buildQueryPrompt(
  basePrompt: string,
  desiredColumns: string[],
  periodLabel: string,
  dimensionLabel: string,
): string {
  const items = desiredColumns.map((s) => s.trim()).filter(Boolean);
  const parts: string[] = [];
  if (items.length > 0) {
    parts.push(
      `Include exactly these columns/metrics in the result, in this order: ${items
        .map((item, index) => `${index + 1}. ${item}`)
        .join("; ")}.`,
    );
  }
  const extra = basePrompt.trim();
  if (extra) parts.push(extra);
  parts.push(`Default period: ${periodLabel}.`);
  if (dimensionLabel.trim()) {
    parts.push(`Primary dimension: ${dimensionLabel.trim()}.`);
  }
  return parts.join(" ");
}

export function AIQueryDesigner({
  open,
  projectId,
  onClose,
  onSaved,
  notify,
}: {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onSaved?: (queryId: number) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const [step, setStep] = useState<"describe" | "preview">("describe");
  const [prompt, setPrompt] = useState("");
  // An explicit, growable list of exact columns/metrics the user wants, as an
  // alternative to describing the whole query as one paragraph and hoping
  // the LLM's column selection matches -- mirrors the dashboard designer's
  // "Specific charts" list.
  const [desiredColumns, setDesiredColumns] = useState<string[]>([""]);
  const [period, setPeriod] = useState("1_year");
  const [dimensionLabel, setDimensionLabel] = useState("");

  useEffect(() => {
    if (!open) return;
    setStep("describe");
    setPrompt("");
    setDesiredColumns([""]);
    setPeriod("1_year");
    setDimensionLabel("");
  }, [open]);

  const periodLabel = PERIODS.find(([value]) => value === period)?.[1] ?? period;
  const effectivePrompt = useMemo(
    () => buildQueryPrompt(prompt, desiredColumns, periodLabel, dimensionLabel),
    [prompt, desiredColumns, periodLabel, dimensionLabel],
  );
  const hasUserInput =
    prompt.trim().length > 0 || desiredColumns.some((c) => c.trim().length > 0);
  const firstDesiredColumn = desiredColumns.map((s) => s.trim()).find(Boolean);

  if (!open) return null;

  if (step === "preview") {
    return (
      <GenerateQueryPreviewModal
        open
        projectId={projectId}
        question={effectivePrompt}
        title={firstDesiredColumn}
        onClose={onClose}
        onBack={() => setStep("describe")}
        onSaved={(queryId) => {
          onSaved?.(queryId);
          onClose();
        }}
        notify={notify}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/35 p-3 sm:p-5">
      <div className="mx-auto my-3 w-full max-w-4xl rounded-xl border border-line-tertiary bg-bg-primary shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line-tertiary px-4 py-4 sm:px-5">
          <div>
            <div className="flex items-center gap-2">
              <IconSparkles size={18} className="text-ai" />
              <h2 className="text-h2 text-ink-primary">Create a query with AI</h2>
            </div>
            <p className="mt-1 text-small text-ink-tertiary">
              Describe the data you need. AI selects the tables, columns, and
              SQL — you review the real result before saving.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI query designer"
            className="shrink-0 rounded p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </header>

        <section className="p-4 sm:p-5">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(260px,.65fr)]">
            <Card className="p-4">
              <div className="mb-4">
                <div className="text-h3 text-ink-primary">
                  Specific columns/metrics (optional)
                </div>
                <p className="mt-1 text-small text-ink-tertiary">
                  Name exact columns or metrics you want instead of leaving
                  the result shape entirely to AI.
                </p>
                <div className="mt-3 space-y-2">
                  {desiredColumns.map((item, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <input
                        value={item}
                        onChange={(event) => {
                          const next = [...desiredColumns];
                          next[index] = event.target.value;
                          setDesiredColumns(next);
                        }}
                        placeholder={
                          index === 0
                            ? "Example: Total revenue by month"
                            : "Example: Backlog by region"
                        }
                        className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                      />
                      {desiredColumns.length > 1 && (
                        <button
                          type="button"
                          onClick={() =>
                            setDesiredColumns(
                              desiredColumns.filter((_, i) => i !== index),
                            )
                          }
                          aria-label="Remove this item"
                          className="shrink-0 rounded p-1.5 text-ink-tertiary hover:bg-bg-secondary hover:text-red-600"
                        >
                          <IconX size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-2"
                  onClick={() => setDesiredColumns([...desiredColumns, ""])}
                >
                  + Add another
                </Button>
              </div>

              <label htmlFor="ai-query-request" className="text-h3 text-ink-primary">
                Additional context (optional)
              </label>
              <p className="mt-1 text-small text-ink-tertiary">
                Use business language. AI selects the tables, columns, and
                calculations.
              </p>
              <textarea
                id="ai-query-request"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={4}
                placeholder="Example: Revenue and backlog by month for the last year, joined on month."
                className="mt-3 w-full resize-y rounded-md border border-line-secondary bg-bg-primary p-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
              />
            </Card>

            <Card className="p-4">
              <h3 className="text-h3 text-ink-primary">Creation context</h3>
              <div className="mt-3 grid gap-3">
                <label className="text-small font-medium text-ink-secondary">
                  Default period
                  <select
                    value={period}
                    onChange={(event) => setPeriod(event.target.value)}
                    className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                  >
                    {PERIODS.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-small font-medium text-ink-secondary">
                  Primary dimension (optional)
                  <input
                    value={dimensionLabel}
                    onChange={(event) => setDimensionLabel(event.target.value)}
                    placeholder="Example: Site, Region, Team"
                    className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                  />
                </label>
              </div>
              <p className="mt-3 text-[11px] leading-4 text-ink-tertiary">
                Tablescope profiles authorized data, validates generated SQL,
                and saves the governed query with lineage automatically.
              </p>
            </Card>
          </div>

          <div className="mt-4 flex justify-end">
            <Button
              variant="primary"
              disabled={!hasUserInput}
              onClick={() => setStep("preview")}
            >
              <IconSparkles size={14} />
              Analyze data &amp; generate query
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}
