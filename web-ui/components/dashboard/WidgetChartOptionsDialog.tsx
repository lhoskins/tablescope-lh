"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { IconX, IconCheck, IconChartBar } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import type { VizCandidate } from "@/lib/api/home-intelligence";
import { OperationalChart, toOperationalChartData } from "./OperationalInsightGrid";
import type { WidgetConfig, WidgetType } from "./types";

/** Chart families `ItsmChart` actually knows how to render (see its
 *  chartType switch). Candidates outside this set (e.g. "kpi", "table",
 *  "combo") are filtered out rather than shown with a misleading preview. */
const SUPPORTED_CHART_TYPES = new Set(["line", "area", "bar", "pie", "heatmap"]);

interface ChartCandidatesResponse {
  chartCandidates?: VizCandidate[];
}

interface WidgetChartOptionsDialogProps {
  widget: WidgetConfig;
  rows: Array<Record<string, unknown>>;
  projectId: number | string;
  open: boolean;
  onClose: () => void;
  onApply: (chartType: string, chartSubtype: string | undefined) => void;
}

/**
 * Lightweight "pick a different compatible chart type" picker for an
 * AI-Designer dashboard widget, reusing the exact ranking Business Insight
 * cards use (`ask_pipeline.resolve_presentation`, via the
 * `chart-candidates` endpoint) rather than a separate heuristic. This is a
 * narrower alternative to "Modify with AI" (which re-derives the whole
 * widget): it only changes chart type/subtype on the widget already fetched
 * data, so previews render instantly through the same `ItsmChart` renderer
 * the dashboard itself uses.
 */
export function WidgetChartOptionsDialog({
  widget,
  rows,
  projectId,
  open,
  onClose,
  onApply,
}: WidgetChartOptionsDialogProps) {
  const [selected, setSelected] = useState<VizCandidate | null>(null);

  const candidatesMutation = useMutation({
    mutationFn: () =>
      apiClient.post<ChartCandidatesResponse>(
        "/api/ai/actions/dashboard-designer/chart-candidates",
        {
          project_id: Number(projectId),
          columns: rows.length > 0 ? Object.keys(rows[0]) : [widget.xColumn, widget.yColumn].filter(Boolean),
          rows,
        },
      ),
  });

  const hasFetched = candidatesMutation.isSuccess;
  const candidates = useMemo(() => {
    const all = candidatesMutation.data?.chartCandidates ?? [];
    return all.filter((c) => SUPPORTED_CHART_TYPES.has(c.decision.chartType));
  }, [candidatesMutation.data]);

  const { mutate: fetchCandidatesFn, reset: resetCandidates } = candidatesMutation;
  useEffect(() => {
    if (!open) return;
    setSelected(null);
    fetchCandidatesFn();
  }, [open, widget.id, fetchCandidatesFn]);

  if (!open) return null;

  const fetchCandidates = () => {
    resetCandidates();
    setSelected(null);
    fetchCandidatesFn();
  };

  const handleApply = () => {
    if (!selected) return;
    onApply(selected.decision.chartType as WidgetType, selected.decision.chartStyle || undefined);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="my-8 flex max-h-[85vh] w-full max-w-4xl flex-col rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex shrink-0 items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconChartBar size={18} className="text-brand-500" />
              Chart options
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              Choose a compatible chart type for &ldquo;{widget.title || "this widget"}&rdquo;.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-md p-1.5 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </div>

        {candidatesMutation.isPending && (
          <div className="flex flex-1 items-center justify-center py-16 text-small text-ink-tertiary">
            Ranking compatible chart types...
          </div>
        )}

        {candidatesMutation.isError && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-small text-ink-tertiary">
            <span>Couldn&apos;t load chart options.</span>
            <button
              type="button"
              onClick={fetchCandidates}
              className="rounded-md border border-line-tertiary px-3 py-1.5 text-[13px] text-ink-secondary hover:bg-bg-secondary"
            >
              Retry
            </button>
          </div>
        )}

        {hasFetched && candidates.length === 0 && (
          <div className="flex flex-1 items-center justify-center py-16 text-small text-ink-tertiary">
            No alternate compatible chart types for this data.
          </div>
        )}

        {hasFetched && candidates.length > 0 && (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
            {candidates.map((candidate, idx) => {
              const isSelected =
                selected?.decision.chartType === candidate.decision.chartType &&
                selected?.decision.chartStyle === candidate.decision.chartStyle;
              const previewWidget: WidgetConfig = {
                ...widget,
                type: candidate.decision.chartType as WidgetType,
              };
              return (
                <button
                  key={`${candidate.decision.chartType}-${candidate.decision.chartStyle || idx}`}
                  type="button"
                  onClick={() => setSelected(candidate)}
                  className={`relative rounded-xl border p-3 text-left transition ${
                    isSelected
                      ? "border-brand-500 ring-1 ring-brand-500"
                      : "border-line-tertiary hover:border-line-secondary"
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[13px] font-medium text-ink-primary">
                      {candidate.decision.chartType}
                      {candidate.decision.chartStyle ? ` — ${candidate.decision.chartStyle}` : ""}
                    </span>
                    {isSelected && <IconCheck size={16} className="text-brand-500" />}
                  </div>
                  <div className="h-[160px] overflow-hidden rounded-md bg-bg-secondary/40">
                    <OperationalChart
                      chart={toOperationalChartData(previewWidget, rows)}
                      className="h-full"
                    />
                  </div>
                  <p className="mt-2 text-[11px] text-ink-tertiary">{candidate.decision.reason}</p>
                </button>
              );
            })}
          </div>
        )}

        <div className="mt-4 flex shrink-0 justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line-tertiary px-3 py-1.5 text-[13px] text-ink-secondary hover:bg-bg-secondary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApply}
            disabled={!selected}
            className="rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-brand-fg hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Apply chart
          </button>
        </div>
      </div>
    </div>
  );
}
