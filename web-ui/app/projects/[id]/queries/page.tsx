"use client";

import { useParams } from "next/navigation";
import { QueriesScreen } from "@/components/tablescope/project/queries-screen";

export default function ProjectQueriesPage() {
  const params = useParams<{ id: string }>();
  return <QueriesScreen projectId={params.id} />;
}
