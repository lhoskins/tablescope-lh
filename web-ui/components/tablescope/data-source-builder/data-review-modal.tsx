"use client";

import { useEffect, useState } from "react";
import { IconLoader2, IconX } from "@tabler/icons-react";
import {
  previewDbTable,
  type TablePreviewResult,
} from "@/lib/api/data-source-builder";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import type { FlatItem } from "./flatten";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Build a preview table from a file source's detected fields + sample values. */
function filePreview(
  fields: { field_name: string; sample_values?: unknown[] }[],
): TablePreviewResult {
  const columns = fields.map((f) => f.field_name);
  const depth = Math.max(0, ...fields.map((f) => f.sample_values?.length ?? 0));
  const rows: unknown[][] = [];
  for (let i = 0; i < depth; i++) {
    rows.push(fields.map((f) => f.sample_values?.[i] ?? null));
  }
  return { columns, rows };
}

export function DataReviewModal({
  item,
  onClose,
}: {
  item: FlatItem;
  onClose: () => void;
}) {
  const source = useBuilderStore((s) =>
    s.sources.find((src) => src.id === item.sourceId),
  );
  const [data, setData] = useState<TablePreviewResult | null>(null);
  const [loading, setLoading] = useState(!item.isFile);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (item.isFile) {
      setData(filePreview(source?.previewFields ?? []));
      setLoading(false);
      return;
    }
    if (!source) return;
    const tableName = item.key.slice(item.sourceId.length + 2);
    setLoading(true);
    setError(null);
    previewDbTable({
      connection_id: source.connectionConfig.connection_id
        ? Number(source.connectionConfig.connection_id)
        : undefined,
      db_type: source.connectionConfig.db_type,
      schema_name: source.connectionConfig.schema_name || undefined,
      table_name: tableName,
      limit: 20,
    })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Could not load data");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item, source]);

  const hasRows = (data?.rows.length ?? 0) > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-bg-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-line-tertiary px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-h3 text-ink-primary">{item.name}</h2>
            <p className="truncate text-caption text-ink-tertiary">
              {item.sourceLabel} · {item.typeLabel}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
          >
            <IconX size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex items-center gap-2 py-10 text-small text-ink-tertiary">
              <IconLoader2 size={16} className="animate-spin" /> Loading data…
            </div>
          ) : error ? (
            <div className="rounded-md border border-danger/40 bg-danger-bg/40 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          ) : !data || data.columns.length === 0 ? (
            <div className="py-10 text-center text-small text-ink-tertiary">
              No preview available for this data source.
            </div>
          ) : (
            <div className="overflow-auto rounded-lg border border-line-tertiary">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="border-b border-line-tertiary bg-bg-secondary/60 text-left text-caption uppercase tracking-wide text-ink-tertiary">
                    {data.columns.map((c) => (
                      <th
                        key={c}
                        className="whitespace-nowrap px-3 py-2 font-medium"
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {hasRows ? (
                    data.rows.map((row, ri) => (
                      <tr
                        key={ri}
                        className="border-b border-line-tertiary last:border-0"
                      >
                        {data.columns.map((_, ci) => (
                          <td
                            key={ci}
                            className="max-w-[280px] truncate px-3 py-1.5 text-ink-secondary"
                            title={cell(row[ci])}
                          >
                            {cell(row[ci])}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td
                        colSpan={data.columns.length}
                        className="px-3 py-8 text-center text-ink-tertiary"
                      >
                        Columns detected, but no sample rows are available.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="border-t border-line-tertiary px-4 py-2 text-caption text-ink-tertiary">
          {data && hasRows
            ? `Showing first ${data.rows.length} row${data.rows.length === 1 ? "" : "s"}.`
            : "Preview"}
        </div>
      </div>
    </div>
  );
}
