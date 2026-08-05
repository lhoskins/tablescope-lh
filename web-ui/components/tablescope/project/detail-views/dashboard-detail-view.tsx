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
} from "@/lib/ui/use-project-data";


// ── Dashboard content ────────────────────────────────────────────────

export function DashboardDetailView({
  projectId,
  dashboard,
  savedQueries,
  datasources,
  onBack,
  onPersisted,
  onPinWidget,
}: {
  projectId: string;
  dashboard: Dashboard;
  savedQueries: SavedQuery[];
  datasources: DataSource[];
  onBack: () => void;
  onPersisted?: () => void;
  onPinWidget?: (widget: WidgetConfig, data: unknown[], dashboardId: number) => void;
}) {
  return (
    <DashboardViewer
      dashboard={dashboard as unknown as ViewerDashboard}
      projectId={Number(projectId)}
      savedQueries={savedQueries.map((q) => ({
        id: q.id,
        name: q.name,
        sql_text: q.sql_text,
      }))}
      datasources={datasources.map((d) => ({
        viewName: d.viewName || d.fileName,
        fileName: d.fileName,
      }))}
      onBack={onBack}
      onPersisted={onPersisted}
      onPinWidget={onPinWidget}
    />
  );
}