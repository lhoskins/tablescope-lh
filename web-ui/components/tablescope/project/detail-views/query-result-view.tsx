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



// ── Query result ─────────────────────────────────────────────────────

export function QueryResultView({
  projectId,
  query,
  backLabel,
  onBack,
  onEdit,
}: {
  projectId: string;
  query: SavedQuery;
  backLabel: string;
  onBack: () => void;
  onEdit?: () => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["query-result", projectId, query.id],
    queryFn: () =>
      apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: safeTableName(query.left_datasource),
        sql: query.sql_text,
        project_id: Number(projectId),
        limit: 500,
      }),
    enabled: Boolean(projectId),
    retry: false,
  });

  const { data: allQueries } = useProjectQueries(projectId);
  const availableQueries = (allQueries ?? []).map((q) => ({
    id: q.id,
    name: q.name,
    sql: q.sql_text,
    leftDatasource: q.left_datasource,
  }));

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-h1 text-ink-primary">{query.name}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-small text-ink-tertiary">
            {query.ai_generated && <Badge tone="ai">AI generated</Badge>}
            {query.is_shared && <Badge tone="success">Shared</Badge>}
            <span>
              {query.left_datasource ?? "—"} · {query.run_count} runs
            </span>
          </p>
        </div>
        {onEdit && (
          <Button variant="secondary" size="sm" onClick={onEdit}>
            <IconPencil size={14} />
            Edit
          </Button>
        )}
      </header>

      <Card className="overflow-hidden p-0">
        {error ? (
          <div className="px-4 py-12 text-center text-small text-danger">
            {(error as Error).message || "Failed to run query."}
          </div>
        ) : (
          <TanStackDataGrid
            columns={data?.columns ?? []}
            rows={data?.rows ?? []}
            loading={isLoading}
            height={520}
            queryId={query.id}
            queryName={query.name}
            projectId={Number(projectId)}
            availableQueries={availableQueries}
            canEditScopes
          />
        )}
      </Card>
    </div>
  );
}