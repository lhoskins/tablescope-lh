"use client";

import { useState } from "react";
import { IconX } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { flattenCreated, type FlatItem } from "./flatten";
import { DataReviewModal } from "./data-review-modal";

function VisibilityBadge({ item }: { item: FlatItem }) {
  return (
    <Badge tone={item.isFile ? "success" : "brand"} size="sm">
      {item.visibility}
    </Badge>
  );
}

export function ActiveSourcesTable() {
  const sources = useBuilderStore((s) => s.sources);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const removeSource = useBuilderStore((s) => s.removeSource);
  const updateTableState = useBuilderStore((s) => s.updateTableState);
  const unmarkCreated = useBuilderStore((s) => s.unmarkCreated);

  const [reviewItem, setReviewItem] = useState<FlatItem | null>(null);

  const items = flattenCreated(sources, createdKeys);

  const remove = (item: FlatItem) => {
    if (item.isFile) {
      removeSource(item.sourceId);
      return;
    }
    const tableName = item.key.slice(item.sourceId.length + 2);
    updateTableState(item.sourceId, tableName, "unselected");
    unmarkCreated(item.key);
  };

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-h3 text-ink-primary">
          Active Data Sources in this Session
        </h3>
        <span className="text-small text-ink-tertiary">
          {items.length} {items.length === 1 ? "source" : "sources"}
        </span>
      </div>

      {items.length === 0 ? (
        <div className="rounded-lg border border-line-tertiary px-4 py-10 text-center text-small text-ink-tertiary">
          No data sources created yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-line-tertiary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-secondary/60 text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Source</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Visibility</th>
                <th className="px-4 py-2.5 text-right font-medium">Columns</th>
                <th className="px-4 py-2.5 text-right font-medium">Size</th>
                <th className="w-10 px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.key}
                  onClick={() => setReviewItem(item)}
                  className="group cursor-pointer border-b border-line-tertiary last:border-0 hover:bg-bg-secondary/40"
                >
                  <td className="px-4 py-2.5 font-medium text-brand-700 hover:underline">
                    {item.name}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {item.sourceLabel}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {item.typeLabel}
                  </td>
                  <td className="px-4 py-2.5">
                    <VisibilityBadge item={item} />
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink-secondary">
                    {item.columns || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink-secondary">
                    {item.sizeOrStatus}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      aria-label={`Remove ${item.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(item);
                      }}
                      className="flex h-6 w-6 items-center justify-center rounded text-ink-tertiary opacity-0 transition-opacity hover:bg-bg-tertiary hover:text-danger group-hover:opacity-100"
                    >
                      <IconX size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {reviewItem && (
        <DataReviewModal
          item={reviewItem}
          onClose={() => setReviewItem(null)}
        />
      )}
    </div>
  );
}
