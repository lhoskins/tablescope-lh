"use client";

import { useProjectDocuments, useProjectQueries } from "@/lib/ui/use-project-data";
import { timeAgo } from "@/lib/ui/format";
import { DocumentDetailView } from "../detail-views/document-detail-view";
import type { WorkspaceCard } from "@/lib/api/workspaces";

/**
 * The `Info` drawer's contents: what is known *about* the selected item, as
 * opposed to the item itself, which is what the Preview pane shows.
 *
 * For a document that's the same AI profile the Documents screen renders --
 * summary, family, type, domain, tags, KPIs, entities, suggested questions --
 * so `DocumentDetailView` is reused wholesale rather than reimplemented.
 */
export function WorkspaceCardInfo({
  projectId,
  card,
}: {
  projectId: string;
  card: WorkspaceCard | null;
}) {
  const { data: documents } = useProjectDocuments(projectId);
  const { data: queries } = useProjectQueries(projectId);

  if (!card) {
    return <Hint>Select a card to see its details.</Hint>;
  }

  if (card.resource_type === "document") {
    const asset = (documents ?? []).find((d) => String(d.id) === card.resource_id);
    if (!asset) return <Hint>{documents == null ? "Loading…" : "Details unavailable."}</Hint>;
    // The detail view brings its own page padding and back bar; neither suits a
    // drawer, so the bar is omitted (no previous screen here) and the padding
    // is pulled back in.
    return (
      <div className="[&>div]:px-3 [&>div]:py-2">
        <DocumentDetailView asset={asset} />
      </div>
    );
  }

  if (card.resource_type === "table") {
    const query = (queries ?? []).find((q) => String(q.id) === card.resource_id);
    if (!query) return <Hint>{queries == null ? "Loading…" : "Details unavailable."}</Hint>;
    return (
      <dl className="space-y-2 px-3 py-2 text-[12px]">
        <Row label="Source">{query.source_name ?? "—"}</Row>
        <Row label="Origin">{query.origin_label}</Row>
        <Row label="Owner">{query.owner_name ?? "—"}</Row>
        <Row label="Runs">{query.run_count}</Row>
        <Row label="Last run">
          {query.last_run_at ? timeAgo(query.last_run_at) : "Never"}
        </Row>
        {query.description && <Row label="Description">{query.description}</Row>}
      </dl>
    );
  }

  return <Hint>No details for this type yet.</Hint>;
}

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 py-4 text-center text-[12px] leading-relaxed text-ink-tertiary">
      {children}
    </p>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-24 shrink-0 text-ink-tertiary">{label}</dt>
      <dd className="min-w-0 flex-1 break-words text-ink-primary">{children}</dd>
    </div>
  );
}
