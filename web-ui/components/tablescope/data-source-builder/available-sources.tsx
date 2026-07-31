"use client";

import { useMemo, useState } from "react";
import { IconCheck, IconSearch } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/badge";
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

function NewBadge({ createdAt }: { createdAt?: string | null }) {
  const loadedAt = createdAt;
  const isNew = Boolean(
    loadedAt &&
      new Date(loadedAt).getTime() > Date.now() - 24 * 60 * 60 * 1000,
  );
  if (!isNew) return null;
  return (
    <Badge tone="brand" size="sm" className="ml-2 shrink-0">
      New
    </Badge>
  );
}

export function AvailableSources() {
  const sources = useBuilderStore((s) => s.sources);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const updateTableState = useBuilderStore((s) => s.updateTableState);

  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();

  const allItems = flattenCreated(sources, createdKeys);
  const items = useMemo(() => {
    if (!query) return allItems;
    return allItems.filter(
      (i) =>
        i.name.toLowerCase().includes(query) ||
        i.sourceLabel.toLowerCase().includes(query) ||
        i.typeLabel.toLowerCase().includes(query),
    );
  }, [allItems, query]);

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
    // h-full is required so the inner flex-1 overflow-y-auto list can scroll:
    // this component is wrapped in a grid item (unlike ProjectsColumn, which IS
    // the grid item), so without it the root sizes to content and is clipped.
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-1 px-1">
        <h3 className="text-h3 text-ink-primary">Available Data Sources</h3>
        <p className="text-small text-ink-tertiary">
          Select the data sources to assign to projects
        </p>
      </div>

      {allItems.length === 0 ? (
        <div className="mt-3 rounded-lg border border-line-tertiary px-4 py-10 text-center text-small text-ink-tertiary">
          No data sources created yet. Go back to Step 1 to create some.
        </div>
      ) : (
        <>
          <div className="mb-2 px-1">
            <div className="flex items-center gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 focus-within:border-brand-100 focus-within:ring-2 focus-within:ring-brand-100">
              <IconSearch size={16} className="text-ink-tertiary" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search data sources"
                className="min-w-0 flex-1 bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary outline-none"
              />
            </div>
          </div>

          <button
            type="button"
            onClick={toggleAll}
            className="mb-2 mt-2 flex items-center gap-2.5 border-b border-line-tertiary px-1 pb-2 text-left text-[13px] font-medium text-brand-700"
          >
            <Checkbox checked={allSelected} />
            {selectedCount} of {items.length} selected
          </button>

          {items.length === 0 ? (
            <div className="py-6 text-center text-small text-ink-tertiary">
              No data sources match “{search}”.
            </div>
          ) : (
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
                    <span className="flex items-center">
                      <span className="block truncate font-mono text-[13px] text-ink-primary">
                        {item.name}
                      </span>
                      <NewBadge createdAt={item.createdAt} />
                    </span>
                    <span className="block truncate text-caption text-ink-tertiary">
                      {item.typeLabel}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
