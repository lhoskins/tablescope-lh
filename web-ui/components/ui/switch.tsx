"use client";

import { cn } from "@/lib/cn";

export interface SwitchProps {
  id?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  pending?: boolean;
  onLabel?: string;
  offLabel?: string;
}

export function Switch({
  id,
  checked,
  onChange,
  label,
  description,
  disabled,
  pending,
  onLabel = "On",
  offLabel = "Off",
}: SwitchProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (!disabled && !pending) onChange(!checked);
    }
  };

  return (
    <div className="flex items-start justify-between gap-4">
      <div className={cn("flex-1", (label || description) && "pr-2")}>
        {label && (
          <label
            htmlFor={id}
            className="block text-sm font-medium text-ink-primary"
          >
            {label}
          </label>
        )}
        {description && (
          <p className="mt-0.5 text-xs text-ink-tertiary">{description}</p>
        )}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled || pending}
        onClick={() => onChange(!checked)}
        onKeyDown={handleKeyDown}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
          checked ? "bg-brand" : "bg-bg-tertiary",
          (disabled || pending) && "cursor-not-allowed opacity-60",
        )}
      >
        <span
          className={cn(
            "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-5" : "translate-x-0.5",
          )}
        />
      </button>
      <span
        className={cn(
          "w-8 text-right text-xs font-medium",
          checked ? "text-brand" : "text-ink-tertiary",
        )}
        aria-hidden="true"
      >
        {pending ? "…" : checked ? onLabel : offLabel}
      </span>
    </div>
  );
}
