import { cn } from "@/lib/cn";

interface StatTileProps {
  label: string;
  value: string | number;
  hint?: string;
  hintTone?: "default" | "success";
  className?: string;
}

export function StatTile({
  label,
  value,
  hint,
  hintTone = "default",
  className,
}: StatTileProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-line-tertiary bg-bg-primary p-4",
        className,
      )}
    >
      <div className="text-caption uppercase tracking-wide text-ink-tertiary">
        {label}
      </div>
      <div className="mt-1 text-h1 text-ink-primary">{value}</div>
      {hint && (
        <div
          className={cn(
            "mt-1 text-small",
            hintTone === "success" ? "text-success" : "text-ink-tertiary",
          )}
        >
          {hint}
        </div>
      )}
    </div>
  );
}
