"use client";

import { useMemo } from "react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { DocumentsTab } from "@/components/documents/DocumentsTab";
import { getUserMeta } from "@/lib/auth";
import { useProjectDocuments } from "@/lib/ui/use-project-data";

export function DocumentsScreen({
  projectId,
  documentId,
}: {
  projectId: string;
  documentId?: string;
}) {
  const { data } = useProjectDocuments(projectId);
  const rows = useMemo(() => data ?? [], [data]);
  const canEdit = (getUserMeta()?.role ?? "viewer") !== "viewer";

  const activeDocument = documentId
    ? rows.find((d) => d.id === Number(documentId)) ?? null
    : null;

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-documents"
      breadcrumbLabel="Documents"
      workspaceItem={
        activeDocument
          ? {
              type: "document",
              id: String(activeDocument.id),
              numericId: activeDocument.id,
              label: activeDocument.title,
              href: `/projects/${projectId}/documents/${activeDocument.id}`,
            }
          : null
      }
    >
      <DocumentsTab
        projectId={Number(projectId)}
        canEdit={canEdit}
        initialExpandedId={documentId ? Number(documentId) : undefined}
      />
    </ProjectShell>
  );
}
