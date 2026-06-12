"use client";

import { useState } from "react";
import type { DashboardDateRange } from "./types";
import { DATE_PRESETS, resolveDatePreset, type DatePresetId } from "@/lib/dashboard/dateRange";

type Props = {
  value: DashboardDateRange | null;
  onChange: (range: DashboardDateRange | null) => void;
};

/**
 * Dashboard date-range control: a preset dropdown plus custom start/end inputs.
 * Emits a resolved {preset, start, end} range, or null for "All time".
 */
export function DateRangeControl({ value, onChange }: Props) {
  const [customStart, setCustomStart] = useState(value?.preset === "custom" ? value.start : "");
  const [customEnd, setCustomEnd] = useState(value?.preset === "custom" ? value.end : "");

  const preset = (value?.preset ?? "all") as DatePresetId;

  const selectPreset = (id: DatePresetId) => {
    if (id === "all") {
      onChange(null);
      return;
    }
    if (id === "custom") {
      if (customStart && customEnd) {
        onChange({ preset: "custom", start: customStart, end: customEnd });
      } else {
        onChange({ preset: "custom", start: customStart, end: customEnd });
      }
      return;
    }
    const resolved = resolveDatePreset(id);
    if (resolved) onChange({ preset: id, start: resolved.start, end: resolved.end });
  };

  const updateCustom = (start: string, end: string) => {
    setCustomStart(start);
    setCustomEnd(end);
    onChange({ preset: "custom", start, end });
  };

  return (
    <div className="flex items-center gap-1.5">
      <svg className="h-3.5 w-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
      <select
        className="rounded-md border border-slate-200 px-2 py-1 text-[11px] font-medium text-slate-700"
        value={preset}
        onChange={(e) => selectPreset(e.target.value as DatePresetId)}
      >
        {DATE_PRESETS.map((p) => (
          <option key={p.id} value={p.id}>{p.label}</option>
        ))}
      </select>
      {preset === "custom" && (
        <div className="flex items-center gap-1">
          <input
            type="date"
            className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
            value={customStart}
            onChange={(e) => updateCustom(e.target.value, customEnd)}
          />
          <span className="text-[10px] text-slate-400">to</span>
          <input
            type="date"
            className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
            value={customEnd}
            onChange={(e) => updateCustom(customStart, e.target.value)}
          />
        </div>
      )}
    </div>
  );
}
