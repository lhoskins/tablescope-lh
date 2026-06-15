import { IconTopologyStar3 } from "@tabler/icons-react";
import { cn } from "@/lib/cn";

export function BrandMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex h-7 w-7 items-center justify-center rounded-md bg-brand text-brand-fg",
        className,
      )}
    >
      <IconTopologyStar3 size={18} stroke={2} />
    </div>
  );
}
