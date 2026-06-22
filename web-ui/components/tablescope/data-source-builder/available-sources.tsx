"use client";

import { IconCheck } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { flattenCreated, type FlatItem } from "./flatten";

function Checkbox({ checked }: { checked: boolean }) {
  return (
    <span
      className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
        checked
          ? "border-brand-500 bg-brand-500 text-white"
          : "border-line-secondary",
      )}
    >
      {checked && <IconCheck size={11} />}
    </span>
  );
}

export function AvailableSources() {
  const sources = useBuilderStore((s) => s.sources);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const updateTableState = useBuilderStore((s) => s.updateTableState);

  const items = flattenCreated(sources, createdKeys);
  const selectedCount = items.filter((i) => i.selected).length;
  const allSelected = items.length > 0 && selectedCount === items.length;

  const tableNameOf = (item: FlatItem) =>
    item.isFile ? item.key.slice(0) : item.key.slice(item.sourceId.length + 2);

  const setItem = (item: FlatItem, selected: boolean) => {
    const tableName = item.isFile
      ? (sources.find((s) => s.id === item.sourceId)?.tables[0]?.tableName ?? "")
      : tableNameOf(item);
    updateTableState(
      item.sourceId,
      tableName,
      selected ? "adding" : "unselected",
    );
  };

  const toggleAll = () => {
    const next = !allSelected;
    for (const item of items) setItem(item, next);
  };

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-1 px-1">
        <h3 className="text-h3 text-ink-primary">Available Data Sources</h3>
        <p className="text-small text-ink-tertiary">
          Select the data sources to assign to projects
        </p>
      </div>

      {items.length === 0 ? (
        <div className="mt-3 rounded-lg border border-line-tertiary px-4 py-10 text-center text-small text-ink-tertiary">
          No data sources created yet. Go back to Step 1 to create some.
        </div>
      ) : (
        <>
          <button
            type="button"
            onClick={toggleAll}
            className="mb-2 mt-2 flex items-center gap-2.5 border-b border-line-tertiary px-1 pb-2 text-left text-[13px] font-medium text-brand-700"
          >
            <Checkbox checked={allSelected} />
            {selectedCount} of {items.length} selected
          </button>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-0.5 py-1">
            {items.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setItem(item, !item.selected)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
                  item.selected
                    ? "border-brand-500/50 bg-brand-50/40"
                    : "border-line-tertiary hover:bg-bg-secondary/50",
                )}
              >
                <Checkbox checked={item.selected} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[13px] text-ink-primary">
                    {item.name}
                  </span>
                  <span className="block truncate text-caption text-ink-tertiary">
                    {item.typeLabel}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
