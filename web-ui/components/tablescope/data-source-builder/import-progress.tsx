"use client";

import { IconAlertTriangle, IconCheck, IconLoader2 } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { STAGE_LABELS, type ImportStage } from "./import-source";

const ORDER: Exclude<ImportStage, "idle" | "error">[] = [
  "validating",
  "connecting",
  "transferring",
  "scanning",
  "profiling",
  "analyzing",
  "ready",
];

/** Stage strip shared by the URL and network import forms. */
export function ImportProgress({
  stage,
  error,
  onCancel,
  onRetry,
}: {
  stage: ImportStage;
  error?: string | null;
  onCancel?: () => void;
  onRetry?: () => void;
}) {
  if (stage === "idle") return null;

  if (stage === "error") {
    return (
      <div className="mt-3 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2">
        <IconAlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <p className="text-small text-danger">{error ?? "Import failed."}</p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-1 text-caption font-medium text-brand-700 underline"
            >
              Try again
            </button>
          )}
        </div>
      </div>
    );
  }

  const current = ORDER.indexOf(stage as Exclude<ImportStage, "idle" | "error">);

  return (
    <div className="mt-3 rounded-lg border border-line-tertiary bg-bg-secondary/40 px-3 py-2.5">
      <ol className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {ORDER.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li
              key={s}
              aria-current={active ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 text-caption",
                active
                  ? "font-medium text-brand-700"
                  : done
                    ? "text-ink-secondary"
                    : "text-ink-tertiary",
              )}
            >
              {done ? (
                <IconCheck size={13} className="text-success" />
              ) : active ? (
                <IconLoader2 size={13} className="animate-spin" />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-line-secondary" />
              )}
              {STAGE_LABELS[s]}
            </li>
          );
        })}
      </ol>
      {onCancel && stage !== "ready" && (
        <button
          type="button"
          onClick={onCancel}
          className="mt-2 text-caption font-medium text-ink-tertiary underline"
        >
          Cancel import
        </button>
      )}
    </div>
  );
}
