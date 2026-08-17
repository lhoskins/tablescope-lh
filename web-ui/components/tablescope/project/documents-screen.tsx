"use client";

import { useMemo } from "react";
import {
  IconFileText,
  IconBrain,
  IconArrowsExchange,
  IconSparkles,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { DocumentsTab } from "@/components/documents/DocumentsTab";
import { getUserMeta } from "@/lib/auth";
import {
  useProjectDocuments,
  relationshipCount,
  extractionCount,
} from "@/lib/ui/use-project-data";
import { StatBar, type StatItem } from "./overview-screen/stat-bar";

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
  const relations = rows.reduce((a, d) => a + (relationshipCount(d) ?? 0), 0);
  const extractions = rows.reduce((a, d) => a + (extractionCount(d) ?? 0), 0);

  const statItems: StatItem[] = [
    {
      key: "total",
      icon: IconFileText,
      iconClass: "bg-brand-50 text-brand-700",
      value: rows.length,
      label: "Total documents",
    },
    {
      key: "indexed",
      icon: IconBrain,
      iconClass: "bg-ai-bg text-ai",
      value: indexed,
      label: "AI indexed",
    },
    {
      key: "relationships",
      icon: IconArrowsExchange,
      iconClass: "bg-success-bg text-success",
      value: relations,
      label: "Relationships",
    },
    {
      key: "extractions",
      icon: IconSparkles,
      iconClass: "bg-warning-bg text-warning",
      value: extractions,
      label: "AI extractions",
    },
  ];

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-documents"
      breadcrumbLabel="Documents"
    >
      <div className="space-y-4">
        <StatBar items={statItems} />

        <DocumentsTab
          projectId={Number(projectId)}
          canEdit={canEdit}
          initialExpandedId={documentId ? Number(documentId) : undefined}
        />
      </div>
    </ProjectShell>
  );
}
