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



// ── Query builder (create a new saved query) ─────────────────────────

export function QueryBuilderCreate({
  projectId,
  datasources,
  backLabel,
  onBack,
  onSaved,
}: {
  projectId: string;
  datasources: DataSource[];
  backLabel: string;
  onBack: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const create = useMutation({
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
      apiClient.post(`/api/projects/${projectId}/queries`, {
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
      onSaved();
    },
  });

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      <QueryBuilder
        projectId={Number(projectId)}
        datasources={datasources.map((d) => ({
          fileName: d.fileName,
          viewName: d.viewName || d.fileName,
          sourceType: d.sourceType,
          dbType: d.dbType,
          connectorType: d.connectorType,
        }))}
        onCancel={onBack}
        onSave={(payload) => create.mutate(payload)}
        isSaving={create.isPending}
        saveLabel="Save query"
      />
    </div>
  );
}