"use client";

import { cn } from "@/lib/cn";
import {
  INTERVAL_OPTIONS,
  RANGE_OPTIONS,
  type TimeSeriesInterval,
  type TimeSeriesRange,
} from "@/lib/insights/time-series";

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

export interface TimeSeriesIntervalRangeControlsProps {
  interval: TimeSeriesInterval;
  range: TimeSeriesRange;
  supportCounts?: Record<string, number>;
  comparisonLabel?: string;
  loading?: boolean;
  onIntervalChange: (interval: TimeSeriesInterval) => void;
  onRangeChange: (range: TimeSeriesRange) => void;
}

export function TimeSeriesIntervalRangeControls({
  interval,
  range,
  supportCounts,
  comparisonLabel,
  loading,
  onIntervalChange,
  onRangeChange,
}: TimeSeriesIntervalRangeControlsProps) {
  const supportFor = (iv: TimeSeriesInterval) => (supportCounts?.[iv] ?? 0) > 0;

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Time series interval and range controls">
      <span className="text-[11px] font-medium text-ink-tertiary">Interval</span>
      <div className="flex items-center gap-1">
        {INTERVAL_OPTIONS.map((opt) => (
          <ToggleButton
            key={opt.value}
            label={opt.label}
            active={interval === opt.value}
            disabled={!supportFor(opt.value)}
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
      {comparisonLabel && (
        <span className="ml-auto text-[11px] text-ink-tertiary">{comparisonLabel}</span>
      )}
      {loading && (
        <span className="text-[11px] text-ink-tertiary" aria-live="polite">
          Loading…
        </span>
      )}
    </div>
  );
}
