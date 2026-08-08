"use client";

import Link from "next/link";
import { IconArrowLeft } from "@tabler/icons-react";

export interface AssistantHeaderProps {
  returnProject?: { id: string | number; name: string } | null;
}

export function AssistantHeader({ returnProject }: AssistantHeaderProps) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      {returnProject ? (
        <Link
          href={`/projects/${returnProject.id}`}
          aria-label={`Back to ${returnProject.name} Overview`}
          className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-ink-secondary hover:bg-bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500"
        >
          <IconArrowLeft size={16} aria-hidden />
          <span className="hidden min-w-0 truncate sm:inline">
            Back to {returnProject.name} Overview
          </span>
          <span className="sm:hidden">Back to Overview</span>
        </Link>
      ) : null}
      <span className="text-h2 min-w-0 truncate text-ink-primary">
        AI Assistant
      </span>
    </div>
  );
}
