"use client";

import { useParams } from "next/navigation";
import { OverviewScreen } from "@/components/tablescope/project/overview-screen";

export default function ProjectOverviewPage() {
  const params = useParams<{ id: string }>();
  return <OverviewScreen projectId={params.id} />;
}
