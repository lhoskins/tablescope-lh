"use client";

/**
 * Compact pill-shaped toggle switch.
 *
 * Mirrors the visual pattern used in the project share toggle: a rounded
 * bordered container with a label and a small sliding knob.
 */
export function PillToggle({
  id,
  checked,
  onChange,
  label,
  ariaLabel,
}: {
  id?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  ariaLabel?: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-line-secondary bg-bg-primary px-2.5 h-8">
      <span className="text-[13px] font-medium text-ink-secondary">{label}</span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel ?? `${label} toggle`}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors ${
          checked ? "bg-brand" : "bg-line-secondary"
        }`}
      >
        <span
          className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-3.5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}
