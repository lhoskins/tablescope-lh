"use client";

import { useParams } from "next/navigation";
import { ProjectInsightScreen } from "@/components/tablescope/project-insight/project-insight-screen";

export default function ProjectInsightPage() {
  const params = useParams<{ id: string }>();
  return <ProjectInsightScreen projectId={params.id} />;
}
