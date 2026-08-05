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
} from "@/lib/ui/use-project-data";import { QueryResult } from "./query-result";
import { safeTableName } from "./safe-table-name";
import { DetailBackBar } from "./detail-back-bar";
import { ColumnTypeEditorModal } from "./column-type-editor-modal";



// ── Data source rows ─────────────────────────────────────────────────

export function DataSourceResultView({
  projectId,
  source,
  backLabel,
  onBack,
}: {
  projectId: string;
  source: DataSource;
  backLabel: string;
  onBack: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const tableName = source.viewName || source.fileName;
  const { data, isLoading, error } = useQuery({
    queryKey: ["datasource-rows", projectId, tableName],
    queryFn: () =>
      apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: safeTableName(tableName),
        project_id: Number(projectId),
        limit: 10000,
      }),
    enabled: Boolean(projectId && tableName),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-tertiary">
            <IconDatabase size={18} />
          </span>
          <div className="min-w-0">
            <h1 className="text-h1 text-ink-primary">{tableName}</h1>
            <p className="mt-0.5 text-small text-ink-tertiary">
              {source.columnTypes?.length ?? 0} columns
            </p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
          <IconPencil size={14} />
          Edit
        </Button>
      </header>

      {editing && (
        <ColumnTypeEditorModal
          projectId={projectId}
          source={source}
          onClose={() => setEditing(false)}
        />
      )}

      <Card className="overflow-hidden p-0">
        {error ? (
          <div className="px-4 py-12 text-center text-small text-danger">
            {(error as Error).message || "Failed to load rows."}
          </div>
        ) : (
          <DataGrid
            columns={data?.columns ?? []}
            rows={data?.rows ?? []}
            loading={isLoading}
            height={520}
          />
        )}
      </Card>
    </div>
  );
}