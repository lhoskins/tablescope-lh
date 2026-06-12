"use client";

import { useState } from "react";
import type { WidgetType, VisualizationOptions, ReferenceLineConfig } from "./types";
import {
  getChartDefinition,
  withDefaults,
  type ChartOptionDefinition,
  type ChartOptionGroup,
} from "@/lib/visualizations/chartRegistry";

type Props = {
  chartType: WidgetType;
  value: VisualizationOptions;
  onChange: (next: VisualizationOptions) => void;
};

const GROUP_LABELS: Record<ChartOptionGroup, string> = {
  chart: "Chart",
  style: "Style",
  advanced: "Advanced",
};

const GROUP_ORDER: ChartOptionGroup[] = ["chart", "style", "advanced"];

/**
 * Registry-driven editor for a widget's visualization options. Renders the
 * option fields declared for the active chart type, grouped into
 * Chart / Style / Advanced sections, plus a dedicated reference-line editor
 * for cartesian charts.
 */
export function ChartOptionsPanel({ chartType, value, onChange }: Props) {
  const def = getChartDefinition(chartType);
  const merged = withDefaults(chartType, value);
  const supportsReferenceLines = ["line", "area", "bar", "combo"].includes(chartType);

  const setOption = (key: keyof VisualizationOptions, v: unknown) => {
    onChange({ ...value, [key]: v });
  };

  if (!def || (def.options.length === 0 && !supportsReferenceLines)) {
    return (
      <p className="text-[10px] text-slate-400">No chart options for this type.</p>
    );
  }

  const renderField = (opt: ChartOptionDefinition) => {
    const current = (merged as Record<string, unknown>)[opt.key];
    if (opt.type === "boolean") {
      return (
        <label key={opt.key} className="flex items-center justify-between gap-2 py-0.5">
          <span className="text-[11px] text-slate-600" title={opt.description}>{opt.label}</span>
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-blue-600"
            checked={!!current}
            onChange={(e) => setOption(opt.key, e.target.checked)}
          />
        </label>
      );
    }
    if (opt.type === "select") {
      return (
        <label key={opt.key} className="flex items-center justify-between gap-2 py-0.5">
          <span className="text-[11px] text-slate-600" title={opt.description}>{opt.label}</span>
          <select
            className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
            value={String(current ?? "")}
            onChange={(e) => setOption(opt.key, e.target.value)}
          >
            {opt.options?.map((o) => (
              <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
            ))}
          </select>
        </label>
      );
    }
    // number
    return (
      <label key={opt.key} className="flex items-center justify-between gap-2 py-0.5">
        <span className="text-[11px] text-slate-600" title={opt.description}>{opt.label}</span>
        <input
          type="number"
          className="w-20 rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
          value={current === undefined || current === null ? "" : Number(current)}
          min={opt.min}
          max={opt.max}
          step={opt.step}
          onChange={(e) => setOption(opt.key, e.target.value === "" ? undefined : Number(e.target.value))}
        />
      </label>
    );
  };

  return (
    <div className="space-y-2.5">
      {GROUP_ORDER.map((group) => {
        const fields = def.options.filter((o) => o.group === group);
        if (fields.length === 0) return null;
        return (
          <div key={group}>
            <p className="mb-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400">{GROUP_LABELS[group]}</p>
            <div className="rounded-md border border-slate-100 bg-slate-50/50 px-2 py-1">
              {fields.map(renderField)}
            </div>
          </div>
        );
      })}

      {supportsReferenceLines && (
        <ReferenceLinesEditor
          value={value.referenceLines ?? []}
          onChange={(refs) => setOption("referenceLines", refs.length > 0 ? refs : undefined)}
        />
      )}
    </div>
  );
}

function ReferenceLinesEditor({
  value,
  onChange,
}: {
  value: ReferenceLineConfig[];
  onChange: (refs: ReferenceLineConfig[]) => void;
}) {
  const [draftValue, setDraftValue] = useState("");
  const [draftLabel, setDraftLabel] = useState("");

  const add = () => {
    const num = Number(draftValue);
    if (!Number.isFinite(num)) return;
    onChange([...value, { axis: "y", value: num, label: draftLabel || undefined }]);
    setDraftValue("");
    setDraftLabel("");
  };

  return (
    <div>
      <p className="mb-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-400">Reference Lines</p>
      <div className="space-y-1 rounded-md border border-slate-100 bg-slate-50/50 px-2 py-1.5">
        {value.map((r, i) => (
          <div key={i} className="flex items-center gap-1 text-[10px]">
            <span className="rounded bg-red-50 px-1.5 py-0.5 font-medium text-red-600">y = {r.value}</span>
            {r.label && <span className="text-slate-500">{r.label}</span>}
            <button
              type="button"
              onClick={() => onChange(value.filter((_, idx) => idx !== i))}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              x
            </button>
          </div>
        ))}
        <div className="flex items-center gap-1">
          <input
            type="number"
            placeholder="value"
            className="w-16 rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
          />
          <input
            placeholder="label (optional)"
            className="flex-1 rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
            value={draftLabel}
            onChange={(e) => setDraftLabel(e.target.value)}
          />
          <button
            type="button"
            onClick={add}
            className="rounded bg-slate-700 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-slate-800"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
