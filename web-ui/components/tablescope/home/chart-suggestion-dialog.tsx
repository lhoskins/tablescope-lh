"use client";

import { useMemo, useState } from "react";
import { IconX, IconCheck, IconChartBar } from "@tabler/icons-react";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import type { WidgetConfig, WidgetType } from "@/components/dashboard/types";
import type { InsightCard, InsightChart, VizCandidate } from "@/lib/api/home-intelligence";
import { applyChartSelection } from "@/lib/api/home-intelligence";
import { useToasts, ToastViewport } from "@/components/ui/toast";

interface ChartSuggestionDialogProps {
  card: InsightCard;
  projectId: number;
  open: boolean;
  onClose: () => void;
  onApplied?: (candidate: VizCandidate) => void;
}

const FALLBACK_CANDIDATES: VizCandidate[] = [
  {
    decision: {
      chartType: "bar",
      chartStyle: "",
      xField: "label",
      yField: "value",
      valueFormat: "number",
      reason: "Category comparison.",
      confidence: 0.7,
    },
    score: 0.7,
    supported: true,
  },
  {
    decision: {
      chartType: "line",
      chartStyle: "",
      xField: "label",
      yField: "value",
      valueFormat: "number",
      reason: "Trend over ordered labels.",
      confidence: 0.6,
    },
    score: 0.6,
    supported: true,
  },
];

function buildPreviewWidget(
  candidate: VizCandidate,
  hasValue2: boolean,
): WidgetConfig {
  const d = candidate.decision;
  const chartType = d.chartType as WidgetType;
  const base: WidgetConfig = {
    id: `preview-${chartType}`,
    type: chartType,
    chartSubtype: (d.chartStyle || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: d.xField || "label",
    xColumnType: chartType === "scatter" ? "number" : "string",
    yColumn: d.yField || "value",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: false, showGrid: false },
    colSpan: 1,
    position: 0,
  };

  if (hasValue2 && (chartType === "combo" || chartType === "scatter")) {
    return { ...base, y2Column: d.y2Field || "value2", y2Aggregation: "sum" };
  }
  return base;
}

export function ChartSuggestionDialog({
  card,
  projectId,
  open,
  onClose,
  onApplied,
}: ChartSuggestionDialogProps) {
  const { toasts, push, dismiss } = useToasts();

  const candidates = card.chartCandidates?.length ? card.chartCandidates : FALLBACK_CANDIDATES;

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

  if (!open) return null;

  const chart = card.chart as InsightChart | null | undefined;
  const series = chart?.data?.series ?? [];
  const hasValue2 = series.some((s) => typeof s.value2 === "number");
  const rows = series.map((s) =>
    hasValue2
      ? { label: s.label, value: s.value, value2: s.value2 ?? 0 }
      : { label: s.label, value: s.value },
  );

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
        className="my-8 w-full max-w-4xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
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

        <div className="grid max-h-[70vh] grid-cols-1 gap-4 overflow-y-auto md:grid-cols-2">
          {candidates.map((candidate, idx) => {
            const widget = buildPreviewWidget(candidate, hasValue2);
            const isSelected = selected?.decision.chartType === candidate.decision.chartType &&
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
                    {candidate.decision.chartStyle ? ` — ${candidate.decision.chartStyle}` : ""}
                  </span>
                  {isSelected && <IconCheck size={16} className="text-brand-500" />}
                </div>
                <div className="h-[160px] rounded-md bg-bg-secondary/40">
                  <WidgetRenderer widget={widget} data={rows} />
                </div>
                <p className="mt-2 text-[11px] text-ink-tertiary">
                  {candidate.decision.reason}
                </p>
              </button>
            );
          })}
        </div>

        <div className="mt-4 flex justify-end gap-2">
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
            className="rounded-md bg-brand-600 px-3 py-1.5 text-[13px] font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-brand-300"
          >
            {saving ? "Saving..." : "Apply chart"}
          </button>
        </div>
      </div>
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
