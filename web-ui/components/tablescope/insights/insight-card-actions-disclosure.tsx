"use client";

import { useId, useState, type ReactNode } from "react";
import { IconChevronDown, IconChevronUp } from "@tabler/icons-react";
import { cn } from "@/lib/cn";

export interface InsightCardActionsDisclosureProps {
  insightId: string;
  sources?: ReactNode;
  actions: ReactNode;
  defaultExpanded?: boolean;
  className?: string;
}

export function InsightCardActionsDisclosure({
  insightId,
  sources,
  actions,
  defaultExpanded = false,
  className,
}: InsightCardActionsDisclosureProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const baseId = useId();
  const contentId = `insight-actions-${insightId}-${baseId}`;

  const hasSources = sources != null && sources !== false;

  return (
    <div className={cn("mt-3 flex flex-col items-start", className)}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={contentId}
        title={
          expanded
            ? "Hide data sources and actions"
            : "Show data sources and actions"
        }
        onClick={() => setExpanded((value) => !value)}
        className="inline-flex min-h-8 items-center gap-1.5 bg-transparent px-2 py-1 text-small font-medium text-ink-tertiary transition-colors hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
      >
        <span>More Actions</span>
        {expanded ? (
          <IconChevronUp size={16} className="text-current" aria-hidden />
        ) : (
          <IconChevronDown size={16} className="text-current" aria-hidden />
        )}
      </button>

      {expanded && (
        <div
          id={contentId}
          className="mt-3 w-full border-t border-line-tertiary pt-3"
        >
          {hasSources && (
            <div className="flex flex-wrap items-center gap-2 text-small text-ink-tertiary">
              {sources}
            </div>
          )}
          <div
            className={cn(
              "flex flex-wrap items-center gap-2",
              hasSources && "mt-2.5",
            )}
          >
            {actions}
          </div>
        </div>
      )}
    </div>
  );
}
