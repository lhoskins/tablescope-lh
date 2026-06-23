"use client";

import { useParams } from "next/navigation";
import { DashboardsScreen } from "@/components/tablescope/project/dashboards-screen";

export default function ProjectDashboardDetailPage() {
  const params = useParams<{ id: string; dashboardId: string }>();
  return (
    <DashboardsScreen projectId={params.id} dashboardId={params.dashboardId} />
  );
}
