"use client";

import { useMemo, useState } from "react";
import { IconSearch, IconUpload, IconFileText } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectDocuments,
  relationshipCount,
  extractionCount,
  type ProjectAsset,
} from "@/lib/ui/use-project-data";
import { DocumentDetailView } from "@/components/tablescope/project/detail-views";

type Filter = "all" | "pdf" | "docx" | "xlsx" | "indexed";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pdf", label: "PDF" },
  { key: "docx", label: "DOCX" },
  { key: "xlsx", label: "XLSX" },
  { key: "indexed", label: "AI indexed" },
];

const INDEXED = new Set(["ready", "indexed", "completed", "complete"]);
const PENDING = new Set(["processing", "extracting", "indexing", "pending", "chunking"]);

function fileType(a: ProjectAsset): string {
  if (a.file_extension) return a.file_extension.replace(".", "").toUpperCase();
  if (a.content_type?.includes("pdf")) return "PDF";
  return "FILE";
}

function typeTone(type: string): BadgeProps["tone"] {
  switch (type) {
    case "PDF":
      return "warning";
    case "DOCX":
    case "DOC":
      return "brand";
    case "XLSX":
    case "CSV":
      return "success";
    default:
      return "neutral";
  }
}

function statusBadge(a: ProjectAsset): { label: string; tone: BadgeProps["tone"] } {
  const s = a.ai_status.toLowerCase();
  if (INDEXED.has(s)) return { label: "Indexed", tone: "brand" };
  if (PENDING.has(s)) return { label: "Indexing…", tone: "outline" };
  if (s === "failed") return { label: "Failed", tone: "danger" };
  return { label: a.ai_status, tone: "neutral" };
}

function humanSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function metaString(meta: Record<string, unknown>, key: string): string | null {
  const v = meta?.[key];
  return typeof v === "string" ? v : null;
}

export function DocumentsScreen({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectDocuments(projectId);
  const rows = useMemo(() => data ?? [], [data]);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((a) => {
      const type = fileType(a).toLowerCase();
      if (filter === "pdf" && type !== "pdf") return false;
      if (filter === "docx" && type !== "docx" && type !== "doc") return false;
      if (filter === "xlsx" && type !== "xlsx" && type !== "csv") return false;
      if (filter === "indexed" && !INDEXED.has(a.ai_status.toLowerCase()))
        return false;
      if (term && !a.title.toLowerCase().includes(term)) return false;
      return true;
    });
  }, [rows, filter, search]);

  const selected =
    rows.find((a) => a.id === selectedId) ?? filtered[0] ?? rows[0] ?? null;
  const detail = rows.find((a) => a.id === detailId) ?? null;

  const indexed = rows.filter((a) => INDEXED.has(a.ai_status.toLowerCase())).length;
  const pending = rows.filter((a) => PENDING.has(a.ai_status.toLowerCase())).length;
  const relations = rows.reduce((a, d) => a + (relationshipCount(d) ?? 0), 0);
  const extractions = rows.reduce((a, d) => a + (extractionCount(d) ?? 0), 0);

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-documents"
      breadcrumbLabel="Documents"
      actions={
        <>
          <Button variant="secondary">
            <IconSearch size={14} />
            Search docs
          </Button>
          <Button variant="primary">
            <IconUpload size={14} />
            Upload
          </Button>
        </>
      }
      contextPanel={<DocumentDetailPanel asset={detail ?? selected} />}
    >
      {detail ? (
        <DocumentDetailView
          asset={detail}
          backLabel="Documents"
          onBack={() => setDetailId(null)}
        />
      ) : (
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

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <IconSearch
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search document content…"
              className="h-8 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
            />
          </div>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "h-8 rounded-md border px-3 text-[12px] font-medium",
                filter === f.key
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-line-secondary bg-bg-primary text-ink-secondary hover:bg-bg-secondary",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        <Card>
          <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
            <span className="text-h3 text-ink-primary">All Documents</span>
            <span className="text-small text-ink-tertiary">
              {filtered.length} total
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                  <th className="px-4 py-2 font-medium">Document</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Relationships</th>
                  <th className="px-4 py-2 font-medium">Extractions</th>
                  <th className="px-4 py-2 font-medium">Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => {
                  const active = selected?.id === a.id;
                  const type = fileType(a);
                  const status = statusBadge(a);
                  const rel = relationshipCount(a);
                  const ext = extractionCount(a);
                  return (
                    <tr
                      key={a.id}
                      onClick={() => {
                        setSelectedId(a.id);
                        setDetailId(a.id);
                      }}
                      className={cn(
                        "cursor-pointer border-b border-line-tertiary last:border-0",
                        active ? "bg-brand-50/60" : "hover:bg-bg-secondary",
                      )}
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2.5">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-bg-secondary text-ink-tertiary">
                            <IconFileText size={15} />
                          </span>
                          <div className="min-w-0">
                            <div
                              className={cn(
                                "truncate font-medium",
                                active ? "text-brand-700" : "text-ink-primary",
                              )}
                            >
                              {a.title}
                            </div>
                            <div className="text-small text-ink-tertiary">
                              {humanSize(a.file_size_bytes)}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={typeTone(type)}>{type}</Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={status.tone}>{status.label}</Badge>
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {rel == null ? "—" : `${rel} links`}
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {ext == null ? "—" : ext}
                      </td>
                      <td className="px-4 py-2.5 text-ink-tertiary">
                        {timeAgo(a.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!isLoading && filtered.length === 0 && (
              <div className="px-4 py-12 text-center text-small text-ink-tertiary">
                {rows.length === 0
                  ? "No documents yet. Upload a document to start AI indexing."
                  : "No documents match your filters."}
              </div>
            )}
            {isLoading && (
              <div className="px-4 py-12 text-center text-small text-ink-tertiary">
                Loading documents…
              </div>
            )}
          </div>
        </Card>
      </div>
      )}
    </ProjectShell>
  );
}

function DocumentDetailPanel({ asset }: { asset: ProjectAsset | null }) {
  if (!asset) {
    return (
      <ContextPanel
        title="Document Detail"
        askPlaceholder="Ask about this document…"
      >
        <div className="px-1 py-8 text-center text-small text-ink-tertiary">
          Select a document to see its AI summary and extractions.
        </div>
      </ContextPanel>
    );
  }
  const meta = asset.ai_metadata ?? {};
  const vendor = metaString(meta, "vendor");
  const signed = metaString(meta, "signed");
  const expires = metaString(meta, "expires");
  const type = fileType(asset);
  return (
    <ContextPanel title="Document Detail" askPlaceholder="Ask about this document…">
      {asset.ai_summary && (
        <div className="rounded-lg border border-brand-100 bg-brand-50/60 p-3 text-[13px] leading-relaxed text-ink-primary">
          {asset.ai_summary}
        </div>
      )}

      <ContextSection title="Document Metadata">
        <dl className="space-y-1 text-[13px]">
          <Row label="Type" value={type} />
          <Row label="Size" value={humanSize(asset.file_size_bytes)} />
          <Row label="Status" value={statusBadge(asset).label} />
          {vendor && <Row label="Vendor" value={vendor} />}
          {signed && <Row label="Signed" value={signed} />}
          {expires && <Row label="Expires" value={expires} />}
          <Row label="Uploaded" value={timeAgo(asset.created_at)} />
        </dl>
      </ContextSection>
    </ContextPanel>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-ink-tertiary">{label}</dt>
      <dd className="truncate text-ink-primary">{value}</dd>
    </div>
  );
}
