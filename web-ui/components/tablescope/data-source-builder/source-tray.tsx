"use client";

import { useState } from "react";
import { IconPlus, IconX } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { cn } from "@/lib/cn";
import {
  useBuilderStore,
  type SessionSource,
} from "@/lib/stores/data-source-builder-store";
import {
  CONNECTOR_LABELS,
  connectorIcon,
  STATUS_TONE,
  type SourceCategory,
} from "./util";

function selectionLabel(source: SessionSource): string {
  if (source.isFileUpload) {
    return `${source.fileMetadata?.rows ?? 0} rows`;
  }
  const adding = source.tables.filter((t) => t.state === "adding").length;
  return `${adding} selected`;
}

export function SourceTray({
  onAddSource,
}: {
  onAddSource: (category?: SourceCategory) => void;
}) {
  const sources = useBuilderStore((s) => s.sources);
  const activeSourceId = useBuilderStore((s) => s.activeSourceId);
  const setActiveSource = useBuilderStore((s) => s.setActiveSource);
  const removeSource = useBuilderStore((s) => s.removeSource);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);

  const [confirmId, setConfirmId] = useState<string | null>(null);

  const requestRemove = (source: SessionSource) => {
    const pending = getPendingChanges();
    const hasPending =
      pending.adding.some((a) => a.source.id === source.id) ||
      source.tables.some((t) => t.state === "adding");
    if (hasPending) {
      setConfirmId(source.id);
    } else {
      removeSource(source.id);
    }
  };

  return (
    <div className="border-b border-line-tertiary bg-bg-primary px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-caption uppercase tracking-wide text-ink-tertiary">
          Active data sources in this session
        </span>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onAddSource()}
          className="gap-1"
        >
          <IconPlus size={14} /> Add source
        </Button>
      </div>

      <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
        {sources.length === 0 ? (
          <div className="flex items-center gap-2">
            <span className="text-small text-ink-tertiary">
              No sources yet.
            </span>
            {(
              [
                ["Database", "database"],
                ["API", "api"],
                ["File", "file"],
                ["Warehouse", "warehouse"],
              ] as [string, SourceCategory][]
            ).map(([label, cat]) => (
              <Button
                key={cat}
                variant="ghost"
                size="sm"
                onClick={() => onAddSource(cat)}
              >
                {label}
              </Button>
            ))}
          </div>
        ) : (
          sources.map((source) => {
            const Icon = connectorIcon(source.sourceType);
            const status = STATUS_TONE[source.status];
            const isActive = source.id === activeSourceId;
            return (
              <button
                key={source.id}
                type="button"
                onClick={() => setActiveSource(source.id)}
                className={cn(
                  "flex min-w-[220px] items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors",
                  isActive
                    ? "border-brand-500 bg-brand-50/40 ring-1 ring-brand/20"
                    : "border-line-secondary bg-bg-primary hover:bg-bg-secondary",
                )}
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-bg-secondary text-ink-secondary">
                  <Icon size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-[13px] font-semibold text-ink-primary">
                      {source.displayName}
                    </span>
                    <Badge tone={status.tone} size="sm">
                      {status.label}
                    </Badge>
                  </span>
                  <span className="block truncate text-caption text-ink-tertiary">
                    {CONNECTOR_LABELS[source.sourceType]} ·{" "}
                    {selectionLabel(source)}
                  </span>
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={`Remove ${source.displayName} from session`}
                  onClick={(e) => {
                    e.stopPropagation();
                    requestRemove(source);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.stopPropagation();
                      requestRemove(source);
                    }
                  }}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-ink-tertiary hover:bg-bg-tertiary hover:text-danger"
                >
                  <IconX size={14} />
                </span>
              </button>
            );
          })
        )}
      </div>

      <ConfirmDialog
        open={confirmId !== null}
        title="Remove source from session?"
        message="This source has pending changes that haven't been applied. Removing it will discard them."
        confirmLabel="Remove"
        onConfirm={() => {
          if (confirmId) removeSource(confirmId);
          setConfirmId(null);
        }}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  );
}
