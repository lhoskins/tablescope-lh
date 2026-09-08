import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * The hint a workspace pane shows while it has nothing in it.
 *
 * Every empty pane routes through here so the five read as one row. They used
 * to disagree in two ways at once -- Documents and Chat sat at the top, Preview
 * and Notes were vertically centred, Actions was top-centred -- which made a
 * fresh workspace look misaligned rather than deliberate.
 *
 * The offset is a fixed distance from the top of the pane body, not a fraction
 * of it. A fraction looks equivalent and isn't: Chat and Actions are shorter
 * than their neighbours because a composer and an action input sit under them,
 * so the same percentage resolved ~15-30px higher in those two and the row came
 * out ragged. A fixed offset is measured from the one edge all five panes share.
 *
 * Callers whose own container carries top padding cancel it with a negative
 * margin (see the `-mt-*` at the Chat and Actions call sites) so every pane
 * measures from the same y.
 */
export function PaneEmptyState({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="h-56 shrink-0" aria-hidden />
      <div
        className={cn(
          "px-5 text-center text-[12px] leading-relaxed text-ink-tertiary",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
