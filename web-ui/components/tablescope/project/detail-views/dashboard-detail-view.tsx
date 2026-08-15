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
import { ItsmDashboardContent } from "@/components/tablescope/project/itsm-dashboards/ItsmDashboardContent";
import { DashboardGroupNavigation } from "@/components/tablescope/project/dashboard-templates/group-navigation";
import { OperationalInsightWidgets } from "@/components/tablescope/project/dashboard-templates/operational-widgets";
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
  dashboardGroupName,
  dashboardGroup,
  onSelectDashboard,
}: {
  projectId: string;
  dashboard: Dashboard;
  savedQueries: SavedQuery[];
  datasources: DataSource[];
  onBack: () => void;
  onPersisted?: () => void;
  onPinWidget?: (widget: WidgetConfig, data: unknown[], dashboardId: number) => void;
  dashboardGroupName?: string;
  dashboardGroup?: Dashboard[];
  onSelectDashboard?: (dashboardId: number) => void;
}) {
  const itsmPreset =
    typeof dashboard.config === "object" && dashboard.config !== null
      ? (dashboard.config as Record<string, unknown>).itsm_dashboard
      : undefined;

  if (typeof itsmPreset === "string") {
    return (
      <ItsmDashboardContent
        projectId={projectId}
        preset={itsmPreset}
        onBack={onBack}
      />
    );
  }

  return (
    <div>
      {dashboardGroupName && dashboardGroup && onSelectDashboard && (
        <DashboardGroupNavigation
          groupName={dashboardGroupName}
          dashboards={dashboardGroup}
          activeDashboardId={dashboard.id}
          onSelectDashboard={onSelectDashboard}
          onBack={onBack}
        />
      )}
      <OperationalInsightWidgets
        key={`operational-widgets-${dashboard.id}`}
        projectId={projectId}
        dashboard={dashboard}
        onUpdated={onPersisted ? () => onPersisted() : undefined}
      />
      <DashboardViewer
        key={dashboard.id}
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
    </div>
  );
}
