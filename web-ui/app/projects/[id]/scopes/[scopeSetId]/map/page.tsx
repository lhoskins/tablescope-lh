"use client";

import { useParams } from "next/navigation";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ScopeBuilder } from "@/components/scopes/ScopeBuilder";

export default function ScopeBuilderPage() {
  const params = useParams<{ id: string; scopeSetId: string }>();
  return (
    <ProjectShell
      projectId={params.id}
      activeNav="project-scopes"
      breadcrumbLabel="Scope Builder"
    >
      <ScopeBuilder
        projectId={Number(params.id)}
        scopeSetId={Number(params.scopeSetId)}
      />
    </ProjectShell>
  );
}
