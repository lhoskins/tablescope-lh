"use client";

import { IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { TableSelector } from "./table-selector";

export function TableSelectModal({
  sourceId,
  onClose,
}: {
  sourceId: string;
  onClose: () => void;
}) {
  const source = useBuilderStore((s) =>
    s.sources.find((src) => src.id === sourceId),
  );
  const markCreated = useBuilderStore((s) => s.markCreated);
  const unmarkCreated = useBuilderStore((s) => s.unmarkCreated);

  if (!source) return null;

  const adding = source.tables.filter((t) => t.state === "adding").length;

  const done = () => {
    for (const t of source.tables) {
      const key = `${source.id}::${t.tableName}`;
      if (t.state === "adding") markCreated([key]);
      else unmarkCreated(key);
    }
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={done}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-bg-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
          <div>
            <h2 className="text-h3 text-ink-primary">Select tables</h2>
            <p className="text-caption text-ink-tertiary">
              Choose tables from {source.displayName} to create as data sources.
            </p>
          </div>
          <button
            type="button"
            onClick={done}
            aria-label="Close"
            className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
          >
            <IconX size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          <TableSelector source={source} />
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line-tertiary px-4 py-3">
          <Button variant="primary" onClick={done}>
            Done ({adding} selected)
          </Button>
        </div>
      </div>
    </div>
  );
}
