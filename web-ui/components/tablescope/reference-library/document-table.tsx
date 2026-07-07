"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { ReferenceDocument } from "@/lib/api/reference-library";
import { ReferenceDetailDrawer } from "@/components/tablescope/reference-library/detail-drawer";

type StatusTone = "success" | "warning" | "neutral" | "ai";

function displayStatus(d: ReferenceDocument): { label: string; tone: StatusTone } {
  // Metadata-only catalog entries have no attached file yet.
  if (!d.hasFile) return { label: "Needs document", tone: "neutral" };
  if (d.status === "processing") return { label: "Processing", tone: "ai" };
  if (d.status === "active") return { label: "Processed", tone: "success" };
  if (d.status === "draft") {
    return { label: d.aiErrorMessage ? "Error" : "Draft", tone: "warning" };
  }
  return { label: d.status, tone: "neutral" };
}

export function DocumentTable({
  documents,
  loading,
  emptyText = "No references yet.",
  renderActions,
  extraColumn,
  onDocumentChanged,
}: {
  documents: ReferenceDocument[];
  loading?: boolean;
  emptyText?: string;
  renderActions?: (doc: ReferenceDocument) => React.ReactNode;
  extraColumn?: { header: string; render: (doc: ReferenceDocument) => React.ReactNode };
  onDocumentChanged?: () => void;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  return (
    <>
    <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
            <th className="px-4 py-2.5 font-medium">Title</th>
            <th className="px-4 py-2.5 font-medium">Issuing body</th>
            <th className="px-4 py-2.5 font-medium">Domain</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            {extraColumn && <th className="px-4 py-2.5 font-medium">{extraColumn.header}</th>}
            {renderActions && <th className="px-4 py-2.5 font-medium text-right">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr>
              <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
                Loading…
              </td>
            </tr>
          )}
          {!loading && documents.length === 0 && (
            <tr>
              <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
                {emptyText}
              </td>
            </tr>
          )}
          {documents.map((d) => (
            <tr
              key={`${d.id}-${d.assignmentId ?? ""}`}
              onClick={() => setSelectedId(d.id)}
              className="cursor-pointer border-b border-line-tertiary last:border-0 hover:bg-bg-tertiary"
            >
              <td className="px-4 py-3">
                <div className="font-medium text-ink-primary">{d.title}</div>
                {d.versionLabel && (
                  <div className="text-[11px] text-ink-tertiary">{d.versionLabel}</div>
                )}
                {d.aiSummary && (
                  <div className="mt-0.5 max-w-md text-[12px] text-ink-secondary line-clamp-2">
                    {d.aiSummary}
                  </div>
                )}
              </td>
              <td className="px-4 py-3 text-ink-secondary">{d.issuingBody ?? "—"}</td>
              <td className="px-4 py-3">
                {d.domainTag ? (
                  <Badge tone="outline">{d.domainTag}</Badge>
                ) : (
                  <span className="text-ink-tertiary">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                {(() => {
                  const s = displayStatus(d);
                  return <Badge tone={s.tone}>{s.label}</Badge>;
                })()}
                {d.tierBadge && (
                  <Badge tone="brand" className="ml-1">{d.tierBadge}</Badge>
                )}
              </td>
              {extraColumn && (
                <td
                  className="px-4 py-3"
                  onClick={(e) => e.stopPropagation()}
                >
                  {extraColumn.render(d)}
                </td>
              )}
              {renderActions && (
                <td
                  className="px-4 py-3 text-right"
                  onClick={(e) => e.stopPropagation()}
                >
                  {renderActions(d)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
      {selectedId != null && (
        <ReferenceDetailDrawer
          documentId={selectedId}
          onClose={() => setSelectedId(null)}
          onChanged={onDocumentChanged}
        />
      )}
    </>
  );
}
