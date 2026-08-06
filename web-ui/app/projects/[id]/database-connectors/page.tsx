"use client";

import { useParams } from "next/navigation";
import { ProjectToolScreen } from "@/components/tablescope/project/project-tool-screen";
import { DatabaseConnectorsWorkspace } from "@/components/tablescope/database-connectors/workspace";

export default function ProjectDatabaseConnectorsPage() {
  const { id: projectId } = useParams<{ id: string }>();

  return (
    <ProjectToolScreen
      projectId={projectId}
      activeNav="project-database-connectors"
      breadcrumbLabel="Database Connectors"
    >
      <DatabaseConnectorsWorkspace projectId={projectId} />
    </ProjectToolScreen>
  );
}
