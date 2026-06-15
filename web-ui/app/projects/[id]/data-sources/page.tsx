"use client";

import { useParams } from "next/navigation";
import { DataSourcesScreen } from "@/components/tablescope/project/data-sources-screen";

export default function ProjectDataSourcesPage() {
  const params = useParams<{ id: string }>();
  return <DataSourcesScreen projectId={params.id} />;
}
