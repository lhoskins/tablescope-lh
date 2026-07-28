"use client";

import { cn } from "@/lib/cn";
import type { TimeSeriesViewMode } from "@/lib/api/home-intelligence";
import type {
  TimeSeriesInterval,
  TimeSeriesRange,
} from "@/lib/insights/time-series";
import { TimeSeriesIntervalRangeControls } from "./time-series-interval-range-controls";

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
  const supportCounts = supportedIntervals?.reduce(
    (acc, iv) => {
      acc[iv] = (acc[iv] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

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
        <div className="ml-1 flex items-center">
          <TimeSeriesIntervalRangeControls
            interval={interval}
            range={range}
            supportCounts={supportCounts}
            comparisonLabel={mode === "percent_change" ? comparisonLabel : undefined}
            loading={loading}
            onIntervalChange={onIntervalChange}
            onRangeChange={onRangeChange}
          />
        </div>
      </div>
    </div>
  );
}
