"use client";

import { IconCheck, IconFileSpreadsheet, IconInfoCircle } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import {
  useBuilderStore,
  type SessionSource,
} from "@/lib/stores/data-source-builder-store";
import { formatCount } from "./util";

function formatBytes(bytes?: number): string {
  if (!bytes) return "—";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function FilePreview({ source }: { source: SessionSource }) {
  const toggleTableAi = useBuilderStore((s) => s.toggleTableAi);
  const meta = source.fileMetadata;
  const table = source.tables[0];
  const aiEnabled = table?.aiEnabled ?? true;
  const viewName = source.viewName ?? table?.tableName ?? source.displayName;
  const fields = source.previewFields ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-bg-secondary text-ink-secondary">
            <IconFileSpreadsheet size={18} />
          </span>
          <div>
            <p className="text-[13px] font-semibold text-ink-primary">
              {meta?.name ?? source.displayName}
            </p>
            <p className="text-caption text-ink-tertiary">
              {formatBytes(meta?.sizeBytes)} ·{" "}
              {source.sourceType === "excel" ? "Excel" : "CSV"}
            </p>
          </div>
        </div>
        <Badge tone="success">Ready</Badge>
      </div>

      {/* Excel sheet picker (read-only here; chosen at upload) */}
      {meta?.sheets && meta.sheets.length > 1 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-1">
          {meta.sheets.map((sheet) => (
            <span
              key={sheet}
              className="rounded-md border border-line-secondary bg-bg-secondary px-2 py-1 text-[12px] text-ink-secondary"
            >
              {sheet}
            </span>
          ))}
        </div>
      )}

      {/* Info banner */}
      <div className="mx-4 mb-2 flex items-start gap-2 rounded-md border border-brand-500/30 bg-brand-50/40 px-3 py-2 text-[12px] text-brand-700">
        <IconInfoCircle size={15} className="mt-0.5 shrink-0" />
        <span>
          This file will be added as table:{" "}
          <span className="font-mono font-semibold">{viewName}</span>
        </span>
      </div>

      {/* AI toggle + pre-selected note */}
      <div className="mx-4 mb-2 flex items-center justify-between rounded-md border border-line-tertiary bg-bg-primary px-3 py-2">
        <span className="flex items-center gap-2 text-[12px] text-ink-secondary">
          <span className="flex h-4 w-4 items-center justify-center rounded border border-brand-500 bg-brand-500 text-white">
            <IconCheck size={11} />
          </span>
          Pre-selected — this file is the table.
        </span>
        <label className="flex cursor-pointer items-center gap-2 text-[12px] text-ink-secondary">
          AI profiling
          <input
            type="checkbox"
            checked={aiEnabled}
            onChange={() =>
              table && toggleTableAi(source.id, table.tableName)
            }
            className="h-4 w-4 accent-[var(--brand,#185FA5)]"
          />
        </label>
      </div>

      {/* Column preview */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
              <th className="px-3 py-2 font-medium">Column</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Sample values</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => (
              <tr
                key={f.field_name}
                className="border-b border-line-tertiary last:border-0"
              >
                <td className="px-3 py-2 font-mono text-[12.5px] text-ink-primary">
                  {f.field_name}
                </td>
                <td className="px-3 py-2 text-ink-secondary">
                  {f.detected_type ?? "string"}
                </td>
                <td className="px-3 py-2 text-ink-tertiary">
                  {(f.sample_values ?? [])
                    .slice(0, 3)
                    .map((v) => String(v))
                    .join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {fields.length === 0 && (
          <p className="py-8 text-center text-small text-ink-tertiary">
            Column preview unavailable.
          </p>
        )}
      </div>

      {/* Footer */}
      <div
        className={cn(
          "border-t border-line-tertiary px-4 py-2.5 text-[12px] text-ink-secondary",
        )}
      >
        1 file · {formatCount(meta?.rows ?? 0)} rows ·{" "}
        {meta?.columns.length ?? fields.length} columns — ready to assign
      </div>
    </div>
  );
}
