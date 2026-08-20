"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { IconDatabase, IconPencil, IconArchive } from "@tabler/icons-react";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiClient } from "@/lib/api-client";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { DataSource } from "@/lib/ui/use-project-data";
import { QueryResult } from "./query-result";
import { safeTableName } from "./safe-table-name";
import { DetailBackBar } from "./detail-back-bar";
import { ColumnTypeEditorModal } from "./column-type-editor-modal";

export function DataSourceResultView({
  projectId,
  source,
  backLabel,
  onBack,
  onArchive,
  archiveBusy = false,
  archiveError,
}: {
  projectId: string;
  source: DataSource;
  backLabel: string;
  onBack: () => void;
  onArchive?: () => void;
  archiveBusy?: boolean;
  archiveError?: string | null;
}) {
  const [editing, setEditing] = useState(false);
  const { data: auth } = useCurrentUser();
  const user = auth?.user;
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

  const canArchive =
    onArchive != null &&
    user != null &&
    (user.id === source.ownerId ||
      user.rawRole?.includes("admin") ||
      user.isSuperAdmin);

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
        <div className="flex items-center gap-2">
          {canArchive && (
            <Button
              variant="secondary"
              size="sm"
              disabled={archiveBusy}
              onClick={onArchive}
            >
              <IconArchive size={14} />
              Archive
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
            <IconPencil size={14} />
            Edit
          </Button>
        </div>
      </header>

      {archiveError && (
        <div className="rounded-md border border-danger/30 bg-danger/5 px-4 py-2.5 text-small text-danger">
          {archiveError}
        </div>
      )}

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
            total={data?.total}
          />
        )}
      </Card>
    </div>
  );
}
