"use client";

import { useParams } from "next/navigation";
import { DashboardsScreen } from "@/components/tablescope/project/dashboards-screen";

export default function ProjectDashboardsPage() {
  const params = useParams<{ id: string }>();
  return <DashboardsScreen projectId={params.id} />;
}
