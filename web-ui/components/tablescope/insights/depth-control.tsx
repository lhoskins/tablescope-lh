"use client";

import { useId } from "react";

const GRANULARITY_LABELS: Record<number, string> = {
  1: "Executive",
  2: "Strategic",
  3: "Balanced",
  4: "Detailed",
  5: "Granular",
};

export interface DepthControlProps {
  value: number;
  onChange: (value: number) => void;
  ariaLabel?: string;
  title?: string;
}

/**
 * A browser-consistent depth slider with a visible track, brand fill, and
 * circular thumb. The native range input is kept on top (invisible) so Arrow
 * keys, Home, and End continue to work and screen readers see an accessible
 * control.
 */
export function DepthControl({
  value,
  onChange,
  ariaLabel = "Insight granularity",
  title = "Slide from high-level executive insights to fine-grained, detailed analyses",
}: DepthControlProps) {
  const clamped = Math.min(5, Math.max(1, value));
  const fillPercent = ((clamped - 1) / 4) * 100;
  const labelId = useId();

  return (
    <div
      className="group relative flex items-center gap-2"
      title={title}
    >
      <div className="relative h-5 w-28 focus-within:rounded-full focus-within:ring-2 focus-within:ring-brand-500 focus-within:ring-offset-2 focus-within:ring-offset-bg-secondary">
        {/* Visible track */}
        <div className="pointer-events-none absolute top-1/2 left-0 h-1.5 w-full -translate-y-1/2 rounded-full bg-bg-tertiary" />
        {/* Visible filled portion */}
        <div
          className="pointer-events-none absolute top-1/2 left-0 h-1.5 -translate-y-1/2 rounded-full bg-brand"
          style={{ width: `${fillPercent}%` }}
        />
        {/* Visible thumb */}
        <div
          className="pointer-events-none absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-brand-700 shadow"
          style={{ left: `${fillPercent}%` }}
          aria-hidden
        />
        <input
          type="range"
          min={1}
          max={5}
          step={1}
          value={clamped}
          aria-label={ariaLabel}
          aria-valuetext={GRANULARITY_LABELS[clamped]}
          onChange={(e) => onChange(Number(e.target.value))}
          className="absolute inset-0 m-0 h-full w-full cursor-pointer opacity-0"
        />
      </div>
      <span id={labelId} className="w-20 text-small text-ink-primary">
        {GRANULARITY_LABELS[clamped] ?? "Balanced"}
      </span>
    </div>
  );
}
