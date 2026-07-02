"use client";

import { useParams } from "next/navigation";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { KnowledgeGraphScreen } from "@/components/tablescope/project/knowledge-graph-screen";

export default function ProjectRelationshipMapPage() {
  const params = useParams<{ id: string }>();
  return (
    <ProjectShell
      projectId={params.id}
      activeNav="project-relationship-map"
      breadcrumbLabel="Knowledge Graph"
    >
      <KnowledgeGraphScreen
        projectId={Number(params.id)}
        breadcrumb={["Intelligence", "Knowledge Graph"]}
      />
    </ProjectShell>
  );
}
