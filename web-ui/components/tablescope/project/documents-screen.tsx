"use client";

import { useMemo } from "react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { StatTile } from "@/components/ui/stat-tile";
import { DocumentsTab } from "@/components/documents/DocumentsTab";
import { getUserMeta } from "@/lib/auth";
import {
  useProjectDocuments,
  relationshipCount,
  extractionCount,
} from "@/lib/ui/use-project-data";

const INDEXED = new Set(["ready", "indexed", "completed", "complete", "profiled"]);
const PENDING = new Set([
  "processing",
  "extracting",
  "indexing",
  "pending",
  "chunking",
  "profiling",
]);

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

  const indexed = rows.filter((a) =>
    INDEXED.has(a.ai_status.toLowerCase()),
  ).length;
  const pending = rows.filter((a) =>
    PENDING.has(a.ai_status.toLowerCase()),
  ).length;
  const relations = rows.reduce((a, d) => a + (relationshipCount(d) ?? 0), 0);
  const extractions = rows.reduce((a, d) => a + (extractionCount(d) ?? 0), 0);

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-documents"
      breadcrumbLabel="Documents"
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Total documents" value={rows.length} />
          <StatTile
            label="AI indexed"
            value={indexed}
            hint={`${pending} pending`}
          />
          <StatTile label="Relationships" value={relations} hint="detected" />
          <StatTile
            label="AI extractions"
            value={extractions}
            hint="clauses, KPIs, dates"
          />
        </div>

        <DocumentsTab
          projectId={Number(projectId)}
          canEdit={canEdit}
          initialExpandedId={documentId ? Number(documentId) : undefined}
        />
      </div>
    </ProjectShell>
  );
}
