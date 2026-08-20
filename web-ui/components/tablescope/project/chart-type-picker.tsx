"use client";

import { useState } from "react";
import { IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { CHART_REGISTRY, type ChartTypeDefinition } from "@/lib/visualizations/chartRegistry";
import type { WidgetType } from "@/components/dashboard/types";

/** The chart-type + variant a "Specific charts" row resolved to, or "" for
 * both when left on Auto (the AI/engine decides, matching today's default). */
export interface ChartTypeChoice {
  chartType: WidgetType | "";
  chartSubtype: string;
}

// The families this picker offers -- a curated subset of CHART_REGISTRY
// matching what the dashboard-designer's widgets actually render (no
// sankey/graph/parallel/map/etc., which the AI pipeline never produces).
// "Waterfall" isn't a top-level registry family (it's a bar variant), so
// it's special-cased below to pre-select bar's waterfall variant.
const PICKER_FAMILIES: WidgetType[] = [
  "kpi", "bar", "line", "pie", "area", "combo",
  "scatter", "radar", "treemap", "sunburst", "funnel", "heatmap", "boxplot",
];

function definitionFor(type: WidgetType): ChartTypeDefinition | undefined {
  return CHART_REGISTRY[type];
}

export function ChartTypePicker({
  open,
  initial,
  onClose,
  onPick,
}: {
  open: boolean;
  initial: ChartTypeChoice;
  onClose: () => void;
  onPick: (choice: ChartTypeChoice) => void;
}) {
  const [family, setFamily] = useState<WidgetType>(
    (initial.chartType || "bar") as WidgetType,
  );
  const [subtype, setSubtype] = useState(initial.chartSubtype);

  if (!open) return null;

  const definition = definitionFor(family);
  const variants = definition?.variants ?? [];

  const selectFamily = (type: WidgetType) => {
    setFamily(type);
    setSubtype("");
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/35 p-3"
      onClick={onClose}
    >
      <div
        className="flex max-h-[560px] w-full max-w-2xl flex-col rounded-xl border border-line-tertiary bg-bg-primary shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
          <h2 className="text-h2 text-ink-primary">Choose a chart type</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close chart type picker"
            className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconX size={16} />
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-[168px_1fr]">
          <div className="overflow-y-auto border-r border-line-tertiary p-2">
            <div className="px-2 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-wide text-ink-tertiary">
              Chart families
            </div>
            {PICKER_FAMILIES.map((type) => {
              const def = definitionFor(type);
              if (!def) return null;
              const active = family === type;
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => selectFamily(type)}
                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] font-medium ${
                    active ? "bg-brand-50 text-brand-700" : "text-ink-secondary hover:bg-bg-secondary"
                  }`}
                >
                  <span aria-hidden="true">{def.icon}</span>
                  {def.label}
                </button>
              );
            })}
          </div>

          <div className="overflow-y-auto p-4">
            <div className="mb-3 text-[13px] font-semibold text-ink-primary">
              {definition?.description}
            </div>
            {variants.length === 0 ? (
              <button
                type="button"
                onClick={() => setSubtype("")}
                className="flex w-full flex-col items-center gap-2 rounded-md border-2 border-brand-500 bg-bg-primary p-4 text-center"
              >
                <span className="text-3xl" aria-hidden="true">{definition?.icon}</span>
                <span className="text-[12px] font-medium text-ink-secondary">{definition?.label}</span>
              </button>
            ) : (
              <div className="grid grid-cols-3 gap-2.5">
                {variants.map((variant) => {
                  const selected = subtype === variant.value;
                  return (
                    <button
                      key={variant.value || "default"}
                      type="button"
                      onClick={() => setSubtype(variant.value)}
                      className={`flex flex-col items-center gap-2 rounded-md border p-2.5 text-center ${
                        selected ? "border-brand-500 shadow-[0_0_0_1px_var(--brand-500)]" : "border-line-secondary hover:bg-bg-secondary"
                      }`}
                    >
                      <span className="text-2xl" aria-hidden="true">{definition?.icon}</span>
                      <span className="text-[11px] font-medium text-ink-secondary">{variant.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-line-tertiary px-4 py-3">
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => onPick({ chartType: family, chartSubtype: subtype })}
          >
            OK
          </Button>
        </div>
      </div>
    </div>
  );
}
