import { cn } from "@/lib/cn";

type DotTone = "online" | "offline" | "busy";

const TONE: Record<DotTone, string> = {
  online: "bg-success",
  offline: "bg-ink-tertiary",
  busy: "bg-warning",
};

export function StatusDot({
  tone = "online",
  pulse = false,
  className,
}: {
  tone?: DotTone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 rounded-full",
        TONE[tone],
        pulse && "animate-pulse",
        className,
      )}
    />
  );
}
