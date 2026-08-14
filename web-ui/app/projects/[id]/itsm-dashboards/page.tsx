"use client";

import { useParams } from "next/navigation";
import { ItsmDashboardScreen } from "@/components/tablescope/project/itsm-dashboards/ItsmDashboardScreen";

export default function ItsmDashboardsPage() {
  const params = useParams<{ id: string }>();
  return <ItsmDashboardScreen projectId={params.id} />;
}
