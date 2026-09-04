"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { IconX, IconCheck, IconChartBar } from "@tabler/icons-react";
import { InsightChartView } from "@/components/tablescope/home/intelligence-card";
import type { InsightCard, VizCandidate } from "@/lib/api/home-intelligence";
import { applyChartSelection } from "@/lib/api/home-intelligence";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { apiClient } from "@/lib/api-client";
import {
  applyCandidateToInsightChart,
  insightChartCandidateData,
} from "@/lib/insights/chart-candidate";

interface ChartSuggestionDialogProps {
  card: InsightCard;
  projectId: number;
  open: boolean;
  onClose: () => void;
  onApplied?: (candidate: VizCandidate) => void;
}

interface ChartCandidatesResponse {
  chartCandidates?: VizCandidate[];
}

const FALLBACK_CANDIDATES: VizCandidate[] = [
  // Fallback is intentionally shape-neutral (table only) so the dialog never
  // presents a chart family that the data cannot actually support.
  {
    decision: {
      chartType: "table",
      chartStyle: "",
      xField: "label",
      yField: "value",
      valueFormat: "number",
      reason: "Detail rows when no clear chart shape.",
      confidence: 0.15,
    },
    score: 0.15,
    supported: true,
  },
];

export function ChartSuggestionDialog({
  card,
  projectId,
  open,
  onClose,
  onApplied,
}: ChartSuggestionDialogProps) {
  const { toasts, push, dismiss } = useToasts();

  const candidateData = useMemo(
    () => (card.chart ? insightChartCandidateData(card.chart) : { columns: [], rows: [] }),
    [card.chart],
  );
  const candidatesMutation = useMutation({
    mutationFn: () =>
      apiClient.post<ChartCandidatesResponse>(
        "/api/ai/actions/dashboard-designer/chart-candidates",
        {
          project_id: projectId,
          columns: candidateData.columns,
          rows: candidateData.rows,
        },
      ),
  });
  const { mutate: refreshCandidates } = candidatesMutation;
  useEffect(() => {
    if (!open || candidateData.rows.length === 0) return;
    refreshCandidates();
  }, [open, card.insightId, candidateData.rows.length, refreshCandidates]);

  const candidates = useMemo(() => {
    if (candidatesMutation.isSuccess) {
      return candidatesMutation.data?.chartCandidates ?? [];
    }
    return card.chartCandidates?.length
      ? card.chartCandidates
      : FALLBACK_CANDIDATES;
  }, [
    candidatesMutation.data?.chartCandidates,
    candidatesMutation.isSuccess,
    card.chartCandidates,
  ]);

  const initialSelected = useMemo(() => {
    const currentType = card.chart?.type;
    const currentSubtype = card.chart?.subtype ?? "";
    return (
      candidates.find(
        (c) =>
          c.decision.chartType === currentType &&
          (c.decision.chartStyle ?? "") === currentSubtype,
      ) ?? candidates[0] ?? null
    );
  }, [candidates, card.chart?.type, card.chart?.subtype]);

  const [selected, setSelected] = useState<VizCandidate | null>(initialSelected);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setSelected(initialSelected);
  }, [open, initialSelected]);

  if (!open) return null;

  const handleApply = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await applyChartSelection(card.insightId || card.id, {
        project_id: projectId,
        selection: {
          chartType: selected.decision.chartType,
          chartSubtype: selected.decision.chartStyle,
          visualizationDecision: selected.decision,
        },
      });
      push("Chart selection saved", "success");
      onApplied?.(selected);
      onClose();
    } catch (err) {
      push(`Failed to save chart selection: ${String(err)}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="my-8 flex max-h-[85vh] w-full max-w-5xl flex-col rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex shrink-0 items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconChartBar size={18} className="text-brand-500" />
              Chart suggestion
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              Choose a visualization that best represents this insight.
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

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
          {candidates.map((candidate, idx) => {
            const candidateChart = applyCandidateToInsightChart(card.chart!, candidate);
            const isSelected =
              selected?.decision.chartType === candidate.decision.chartType &&
              selected?.decision.chartStyle === candidate.decision.chartStyle;
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
                    {candidate.decision.chartStyle
                      ? ` — ${candidate.decision.chartStyle}`
                      : ""}
                  </span>
                  {isSelected && <IconCheck size={16} className="text-brand-500" />}
                </div>
                <div className="h-[160px] rounded-md bg-bg-secondary/40 overflow-hidden">
                  <InsightChartView chart={candidateChart} height={160} />
                </div>
                <p className="mt-2 text-[11px] text-ink-tertiary">
                  {candidate.decision.reason}
                </p>
              </button>
            );
          })}
        </div>

        {candidatesMutation.isPending && (
          <p className="mt-2 text-[11px] text-ink-tertiary" role="status">
            Rechecking chart compatibility against this insight&apos;s data...
          </p>
        )}
        {candidatesMutation.isError && (
          <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-warning" role="alert">
            <span>Couldn&apos;t refresh compatibility; showing the saved chart options.</span>
            <button
              type="button"
              className="rounded border border-line-tertiary px-2 py-1 text-ink-secondary"
              onClick={() => refreshCandidates()}
            >
              Retry
            </button>
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
            disabled={!selected || saving}
            className="rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-brand-fg hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "Saving..." : "Apply chart"}
          </button>
        </div>
      </div>
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
