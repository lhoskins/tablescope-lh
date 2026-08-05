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
} from "@/lib/ui/use-project-data";import { DetailBackBar } from "./detail-back-bar";



// ── Query builder (edit an existing saved query) ─────────────────────

export function QueryBuilderEdit({
  projectId,
  query,
  datasources,
  backLabel,
  onBack,
  onSaved,
}: {
  projectId: string;
  query: SavedQuery;
  datasources: DataSource[];
  backLabel: string;
  onBack: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      left_datasource: string;
      right_datasource: string;
      join_type: string;
      left_column: string;
      right_column: string;
      sql_text: string;
    }) =>
      apiClient.put(`/api/projects/${projectId}/queries/${query.id}`, {
        name: payload.name,
        description: payload.description,
        left_datasource: payload.left_datasource || null,
        right_datasource: payload.right_datasource || null,
        join_type: payload.join_type || null,
        left_column: payload.left_column || null,
        right_column: payload.right_column || null,
        sql_text: payload.sql_text,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "queries"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["query-result", projectId, query.id],
      });
      onSaved();
    },
  });

  const invalidateLists = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["project", projectId, "queries"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["query-result", projectId, query.id],
    });
  };

  const archive = useMutation({
    mutationFn: () =>
      apiClient.post(
        `/api/projects/${projectId}/queries/${query.id}/archive`,
        {},
      ),
    onSuccess: async () => {
      setLifecycleError(null);
      await invalidateLists();
      onSaved();
    },
    onError: (e: Error) => setLifecycleError(e.message),
  });

  const restore = useMutation({
    mutationFn: () =>
      apiClient.post(
        `/api/projects/${projectId}/queries/${query.id}/restore`,
        {},
      ),
    onSuccess: async () => {
      setLifecycleError(null);
      await invalidateLists();
      onSaved();
    },
    onError: (e: Error) => setLifecycleError(e.message),
  });

  const remove = useMutation({
    mutationFn: () =>
      apiClient.delete(`/api/projects/${projectId}/queries/${query.id}`),
    onSuccess: async () => {
      setLifecycleError(null);
      await invalidateLists();
      onSaved();
    },
    onError: (e: Error) => setLifecycleError(e.message),
  });

  const handleDelete = () => {
    if (
      window.confirm(
        "Delete this archived query permanently? This cannot be undone.",
      )
    ) {
      remove.mutate();
    }
  };

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      {lifecycleError && (
        <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-2.5 text-small text-danger">
          {lifecycleError}
        </div>
      )}
      <QueryBuilder
        projectId={Number(projectId)}
        datasources={datasources.map((d) => ({
          fileName: d.fileName,
          viewName: d.viewName || d.fileName,
          sourceType: d.sourceType,
          dbType: d.dbType,
          connectorType: d.connectorType,
        }))}
        editQuery={{
          name: query.name,
          description: query.description ?? null,
          left_datasource: query.left_datasource ?? null,
          right_datasource: query.right_datasource ?? null,
          join_type: query.join_type ?? null,
          left_column: query.left_column ?? null,
          right_column: query.right_column ?? null,
          sql_text: query.sql_text ?? null,
        }}
        onCancel={onBack}
        onSave={(payload) => save.mutate(payload)}
        isSaving={save.isPending}
        saveLabel="Save changes"
        isArchived={query.is_archived}
        onArchive={() => archive.mutate()}
        onRestore={() => restore.mutate()}
        onDelete={handleDelete}
        lifecycleBusy={
          archive.isPending || restore.isPending || remove.isPending
        }
      />
    </div>
  );
}