"use client";

import { cn } from "@/lib/cn";
import {
  type TimeSeriesInterval,
  type TimeSeriesRange,
  type TimeSeriesViewMode,
} from "@/lib/api/home-intelligence";

interface TimeSeriesViewControlsProps {
  mode: TimeSeriesViewMode;
  interval: TimeSeriesInterval;
  range: TimeSeriesRange;
  supportedIntervals?: TimeSeriesInterval[];
  comparisonLabel?: string;
  loading?: boolean;
  onModeChange: (mode: TimeSeriesViewMode) => void;
  onIntervalChange: (interval: TimeSeriesInterval) => void;
  onRangeChange: (range: TimeSeriesRange) => void;
}

const MODE_OPTIONS: { value: TimeSeriesViewMode; label: string }[] = [
  { value: "value", label: "Value" },
  { value: "percent_change", label: "% Change" },
];

const INTERVAL_OPTIONS: { value: TimeSeriesInterval; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

const RANGE_OPTIONS: { value: TimeSeriesRange; label: string }[] = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "90d", label: "90D" },
  { value: "1y", label: "1Y" },
  { value: "2y", label: "2Y" },
];

function ToggleButton({
  label,
  active,
  disabled,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
        active
          ? "bg-brand-500 text-white"
          : "border border-line-tertiary bg-bg-primary text-ink-secondary hover:bg-bg-tertiary",
        disabled && "cursor-not-allowed opacity-50",
      )}
      aria-pressed={active}
    >
      {label}
    </button>
  );
}

export function TimeSeriesViewControls({
  mode,
  interval,
  range,
  supportedIntervals,
  comparisonLabel,
  loading,
  onModeChange,
  onIntervalChange,
  onRangeChange,
}: TimeSeriesViewControlsProps) {
  const supported = new Set<TimeSeriesInterval>(supportedIntervals ?? INTERVAL_OPTIONS.map((i) => i.value));

  return (
    <div className="space-y-2" role="group" aria-label="Time series view controls">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium text-ink-tertiary">View</span>
        <div className="flex items-center gap-1">
          {MODE_OPTIONS.map((opt) => (
            <ToggleButton
              key={opt.value}
              label={opt.label}
              active={mode === opt.value}
              onClick={() => onModeChange(opt.value)}
            />
          ))}
        </div>
        <span className="ml-1 text-[11px] font-medium text-ink-tertiary">Interval</span>
        <div className="flex items-center gap-1">
          {INTERVAL_OPTIONS.map((opt) => (
            <ToggleButton
              key={opt.value}
              label={opt.label}
              active={interval === opt.value}
              disabled={!supported.has(opt.value)}
              onClick={() => onIntervalChange(opt.value)}
            />
          ))}
        </div>
        <span className="ml-1 text-[11px] font-medium text-ink-tertiary">Range</span>
        <div className="flex items-center gap-1">
          {RANGE_OPTIONS.map((opt) => (
            <ToggleButton
              key={opt.value}
              label={opt.label}
              active={range === opt.value}
              onClick={() => onRangeChange(opt.value)}
            />
          ))}
        </div>
        {comparisonLabel && mode === "percent_change" && (
          <span className="ml-auto text-[11px] text-ink-tertiary">{comparisonLabel}</span>
        )}
        {loading && (
          <span className="text-[11px] text-ink-tertiary" aria-live="polite">
            Loading…
          </span>
        )}
      </div>
    </div>
  );
}
