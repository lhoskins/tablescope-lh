"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { ProjectToolScreen } from "@/components/tablescope/project/project-tool-screen";
import { DataSourceBuilderWorkspace } from "@/components/tablescope/data-source-builder/workspace";
import { useCurrentUser } from "@/lib/ui/use-shell-data";

function ProjectDataSourceBuilderInner() {
  const { id: projectId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const { data: identity } = useCurrentUser();
  const intent =
    searchParams.get("intent") === "database"
      ? "database"
      : searchParams.get("intent") === "upload"
        ? "upload"
        : undefined;

  return (
    <ProjectToolScreen
      projectId={projectId}
      activeNav="project-data-source-builder"
      breadcrumbLabel="Data Source Builder"
    >
      <DataSourceBuilderWorkspace
        tenantName={identity?.tenant.name ?? ""}
        initialProjectId={projectId}
        intent={intent}
      />
    </ProjectToolScreen>
  );
}

export default function ProjectDataSourceBuilderPage() {
  return (
    <Suspense fallback={null}>
      <ProjectDataSourceBuilderInner />
    </Suspense>
  );
}
