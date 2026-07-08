"use client";

import { useParams } from "next/navigation";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ScopeNavigation } from "@/components/scopes/ScopeNavigation";

export default function ProjectScopesPage() {
  const params = useParams<{ id: string }>();
  return (
    <ProjectShell
      projectId={params.id}
      activeNav="project-scopes"
      breadcrumbLabel="Scopes"
    >
      <ScopeNavigation projectId={Number(params.id)} />
    </ProjectShell>
  );
}
