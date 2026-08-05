"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconSparkles,
  IconSearch,
  IconTarget,
  IconPlus,
  IconArchive,
  IconArrowBackUp,
  IconTrash,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectQueries,
  useProjectArchivedQueries,
  useProjectDataSources,
  type SavedQuery,
} from "@/lib/ui/use-project-data";
import {
  QueryResultView,
  QueryBuilderEdit,
  QueryBuilderCreate,
} from "@/components/tablescope/project/detail-views";import { archivedDate } from "./archived-date";



export function ArchiveCard({
  rows,
  error,
  busyId,
  onRestore,
  onDelete,
}: {
  rows: SavedQuery[];
  error: string | null;
  busyId: number | null;
  onRestore: (id: number) => void;
  onDelete: (q: SavedQuery) => void;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="flex items-center gap-1.5 text-h3 text-ink-primary">
          <IconArchive size={16} className="text-ink-tertiary" />
          Archive
        </span>
        <span className="text-small text-ink-tertiary">
          {rows.length} archived {rows.length === 1 ? "table" : "tables"}
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
              <th className="px-4 py-2 font-medium">Description</th>
              <th className="px-4 py-2 font-medium">Archived</th>
              <th className="px-4 py-2 font-medium">Owner</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => {
              const busy = busyId === q.id;
              return (
                <tr
                  key={q.id}
                  className="border-b border-line-tertiary last:border-0"
                >
                  <td className="px-4 py-2.5 font-medium text-ink-primary">
                    {q.name}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {q.description || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-ink-tertiary">
                    {archivedDate(q.archived_at)}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {q.owner_name ?? "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => onRestore(q.id)}
                      >
                        <IconArrowBackUp size={14} />
                        Restore
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={busy}
                        onClick={() => onDelete(q)}
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
            No archived tables. Archive a table to see it here.
          </div>
        )}
      </div>
    </Card>
  );
}