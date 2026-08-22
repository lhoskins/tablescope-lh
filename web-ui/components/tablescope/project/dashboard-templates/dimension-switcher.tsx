"use client";

import { useState } from "react";
import { IconArrowsRightLeft } from "@tabler/icons-react";

export interface DimensionSwitcherOption {
  id: number;
  label: string;
  isActive: boolean;
}

/** Header control for switching a dashboard's active AI-discovered primary
 * dimension. Renders nothing unless there's more than one full-coverage
 * dimension assigned -- the doc's replacement for the old inline
 * dimension-label-edit pencil, which no longer applies since labels are
 * now set during the AI designer's review step, not edited post-hoc. */
export function DimensionSwitcher({
  options,
  onSelect,
  pending,
}: {
  options: DimensionSwitcherOption[];
  onSelect: (id: number) => void;
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (options.length < 2) return null;
  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={pending}
        className="rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary disabled:opacity-50"
        title="Switch primary dimension"
        aria-label="Switch primary dimension"
      >
        <IconArrowsRightLeft size={12} />
      </button>
      {open && (
        <span className="absolute right-0 top-full z-30 mt-1 w-56 rounded-md border border-line-secondary bg-bg-primary p-1 text-left shadow-lg">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => {
                setOpen(false);
                if (!option.isActive) onSelect(option.id);
              }}
              className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-secondary ${
                option.isActive ? "font-semibold text-brand-700" : "text-ink-primary"
              }`}
            >
              {option.label}
              {option.isActive && <span className="text-[9px] uppercase text-brand-600">Active</span>}
            </button>
          ))}
        </span>
      )}
    </span>
  );
}
