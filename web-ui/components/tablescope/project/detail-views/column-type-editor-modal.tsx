"use client";


import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowLeft,
  IconFileText,
  IconDatabase,
  IconPencil,
  IconX,
} from "@tabler/icons-react";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";
import { DashboardViewer } from "@/components/dashboard/DashboardViewer";
import { QueryBuilder } from "@/components/query-builder/QueryBuilder";
import type { Dashboard as ViewerDashboard, WidgetConfig } from "@/components/dashboard/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  columnLabel,
  useProjectQueries,
  type SavedQuery,
  type DataSource,
  type Dashboard,
  type ProjectAsset,
} from "@/lib/ui/use-project-data";import { FALLBACK_COLUMN_TYPES } from "./fallback-column-types";



export function ColumnTypeEditorModal({
  projectId,
  source,
  onClose,
}: {
  projectId: string;
  source: DataSource;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const initial = (source.columnTypes ?? []).map((c) => columnLabel(c));
  const [types, setTypes] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.map((c) => [c.name, c.type || "string"])),
  );
  const [error, setError] = useState<string | null>(null);

  const { data: typeOptions } = useQuery({
    queryKey: ["column-types", projectId],
    queryFn: () =>
      apiClient.get<string[]>(
        `/api/projects/${projectId}/datasources/column-types`,
      ),
  });
  const options = typeOptions ?? FALLBACK_COLUMN_TYPES;

  const save = useMutation({
    mutationFn: () =>
      apiClient.put(`/api/projects/${projectId}/datasources/columns`, {
        kind: source.id != null ? "db" : "file",
        id: source.id,
        viewName: source.viewName || source.fileName,
        columns: initial.map((c) => ({
          name: c.name,
          type: types[c.name] || c.type || "string",
        })),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "datasources"],
      });
      onClose();
    },
    onError: (e) =>
      setError(e instanceof Error ? e.message : "Failed to save column types"),
  });

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-lg bg-bg-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-3.5">
          <h2 className="text-h2 text-ink-primary">Edit column types</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
            aria-label="Close"
          >
            <IconX size={18} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <p className="mb-3 text-small text-ink-tertiary">
            Choose a type for each column. Saving rebuilds and redeploys the VDB.
          </p>
          {initial.length === 0 ? (
            <div className="py-8 text-center text-small text-ink-tertiary">
              No columns available to edit for this source.
            </div>
          ) : (
            <div className="space-y-2">
              {initial.map((c) => (
                <div
                  key={c.name}
                  className="flex items-center justify-between gap-3"
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink-primary">
                    {c.name}
                  </span>
                  <select
                    value={types[c.name] ?? "string"}
                    onChange={(e) =>
                      setTypes((prev) => ({ ...prev, [c.name]: e.target.value }))
                    }
                    className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                  >
                    {options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
          {error && (
            <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-small text-danger">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line-tertiary px-5 py-3">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setError(null);
              save.mutate();
            }}
            disabled={save.isPending || initial.length === 0}
          >
            {save.isPending ? "Saving…" : "Save columns"}
          </Button>
        </div>
      </div>
    </div>
  );
}