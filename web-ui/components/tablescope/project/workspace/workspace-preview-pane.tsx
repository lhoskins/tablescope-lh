"use client";

import {
  useProjectDashboards,
  useProjectDataSources,
  useProjectDocuments,
  useProjectQueries,
} from "@/lib/ui/use-project-data";
import { DocumentPreview } from "@/components/documents/document-preview";
import { QueryResultView } from "../detail-views/query-result-view";
import { DataSourceResultView } from "../detail-views/data-source-result-view";
import type { WorkspaceCard } from "@/lib/api/workspaces";

/**
 * The Preview pane: whatever card is selected in Documents, shown in full.
 *
 * Every type reuses the view the rest of the app already uses for it, so a
 * table previewed here behaves like the same table opened from the Tables
 * screen -- same result grid, same SQL, same states. The pane only supplies
 * the resolution from a card (a type and an id) to the entity those views
 * expect.
 */
export function WorkspacePreviewPane({
  projectId,
  card,
}: {
  projectId: string;
  card: WorkspaceCard | null;
}) {
  const { data: queries } = useProjectQueries(projectId);
  const { data: documents } = useProjectDocuments(projectId);
  const { data: dataSources } = useProjectDataSources(projectId);
  const { data: dashboards } = useProjectDashboards(projectId);

  if (!card) {
    return (
      <Placeholder>
        Select a document or table in Documents
        <br />
        to preview it here.
      </Placeholder>
    );
  }

  if (card.resource_type === "document") {
    const asset = (documents ?? []).find((d) => String(d.id) === card.resource_id);
    if (!asset) return <Missing label={card.label} loading={documents == null} />;
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <DocumentPreview projectId={Number(projectId)} document={asset} />
      </div>
    );
  }

  if (card.resource_type === "table") {
    const query = (queries ?? []).find((q) => String(q.id) === card.resource_id);
    if (!query) return <Missing label={card.label} loading={queries == null} />;
    return (
      <div className="min-h-0 flex-1 overflow-auto">
        <QueryResultView projectId={projectId} query={query} />
      </div>
    );
  }

  if (card.resource_type === "data_source") {
    const source = (dataSources ?? []).find((d) => String(d.id) === card.resource_id);
    if (!source) return <Missing label={card.label} loading={dataSources == null} />;
    return (
      <div className="min-h-0 flex-1 overflow-auto">
        <DataSourceResultView projectId={projectId} source={source} />
      </div>
    );
  }

  // Dashboards are pinnable but have no pane preview yet. Saying so beats a
  // card that looks clickable and then does nothing.
  const dashboard = (dashboards ?? []).find((d) => String(d.id) === card.resource_id);
  return (
    <Placeholder>
      <strong className="font-semibold text-ink-secondary">
        {dashboard?.name ?? card.label ?? "This dashboard"}
      </strong>
      <br />
      can&apos;t be previewed in a pane yet.
      <br />
      Open it from the Dashboards screen.
    </Placeholder>
  );
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex flex-1 items-center justify-center px-5 text-center text-[12px] leading-relaxed text-ink-tertiary">
      {children}
    </p>
  );
}

/** The card outlived its resource, or the project data hasn't arrived yet. */
function Missing({ label, loading }: { label?: string | null; loading: boolean }) {
  if (loading) return <Placeholder>Loading…</Placeholder>;
  return (
    <Placeholder>
      <strong className="font-semibold text-ink-secondary">{label ?? "This item"}</strong>
      <br />
      is no longer in this project.
    </Placeholder>
  );
}
