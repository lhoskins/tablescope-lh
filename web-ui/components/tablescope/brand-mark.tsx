import { cn } from "@/lib/cn";

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-brand text-sm font-bold text-brand-fg",
        className,
      )}
      aria-label="Tablescope"
      role="img"
    >
      T
    </span>
  );
}
