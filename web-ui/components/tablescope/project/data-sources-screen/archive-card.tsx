"use client";

import { IconArchive, IconArrowBackUp, IconTrash } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SourceIcon } from "./source-icon";
import { sourceTypeLabel } from "./source-type-label";
import type { DataSource } from "@/lib/ui/use-project-data";
import { timeAgo } from "@/lib/ui/format";

export function ArchiveCard({
  rows,
  busyId,
  error,
  onRestore,
  onDelete,
}: {
  rows: DataSource[];
  busyId: string | null;
  error: string | null;
  onRestore: (source: DataSource) => void;
  onDelete: (source: DataSource) => void;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="flex items-center gap-1.5 text-h3 text-ink-primary">
          <IconArchive size={16} className="text-ink-tertiary" />
          Archive
        </span>
        <span className="text-small text-ink-tertiary">
          {rows.length} archived {rows.length === 1 ? "source" : "sources"}
        </span>
      </div>
      {error && (
        <div className="border-b border-danger/30 bg-danger/5 px-4 py-2.5 text-small text-danger">
          {error}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Source</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Archived</th>
              <th className="px-4 py-2 font-medium">Owner</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const busy = busyId === s.lifecycleId;
              return (
                <tr
                  key={s.lifecycleId}
                  className="border-b border-line-tertiary last:border-0"
                >
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <SourceIcon source={s} />
                      <span className="font-medium text-ink-primary">
                        {s.fileName}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {s.viewName || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {sourceTypeLabel(s)}
                  </td>
                  <td className="px-4 py-2.5 text-ink-tertiary">
                    {s.archivedAt ? timeAgo(s.archivedAt) : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {s.ownerName ?? "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => onRestore(s)}
                      >
                        <IconArrowBackUp size={14} />
                        Restore
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={busy}
                        onClick={() => onDelete(s)}
                      >
                        <IconTrash size={14} />
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="px-4 py-12 text-center text-small text-ink-tertiary">
            No archived data sources. Archive a data source to see it here.
          </div>
        )}
      </div>
    </Card>
  );
}
