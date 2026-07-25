"use client";

import { useId, useState, type ReactNode } from "react";
import { IconChevronDown, IconChevronUp } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
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
      <Button
        type="button"
        variant="primary"
        size="sm"
        aria-expanded={expanded}
        aria-controls={contentId}
        title={
          expanded
            ? "Hide data sources and actions"
            : "Show data sources and actions"
        }
        onClick={() => setExpanded((value) => !value)}
        className="rounded-full px-3 py-1 text-[12px]"
      >
        <span>More Actions</span>
        {expanded ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}
      </Button>

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
