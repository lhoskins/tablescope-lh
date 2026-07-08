"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconSparkles,
  IconSearch,
  IconTarget,
  IconPlus,
  IconArchive,
  IconArrowBackUp,
  IconTrash,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectQueries,
  useProjectArchivedQueries,
  useProjectDataSources,
  type SavedQuery,
} from "@/lib/ui/use-project-data";
import {
  QueryResultView,
  QueryBuilderEdit,
  QueryBuilderCreate,
} from "@/components/tablescope/project/detail-views";


type Filter = "all" | "ai" | "manual" | "shared" | "private" | "archive";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ai", label: "AI-generated" },
  { key: "manual", label: "Manual" },
  { key: "shared", label: "Shared" },
  { key: "private", label: "Private" },
  { key: "archive", label: "Archive" },
];

function archivedDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString();
}

function runtimeLabel(ms: number | null): string {
  if (ms == null) return "—";
  return `${(ms / 1000).toFixed(1)}s`;
}

function avgRuntime(rows: SavedQuery[]): string {
  const vals = rows.map((r) => r.avg_runtime_ms).filter((v): v is number => v != null);
  if (vals.length === 0) return "—";
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  return `${(mean / 1000).toFixed(1)}s`;
}

function tablesFor(q: SavedQuery): string {
  return [q.left_datasource, q.right_datasource].filter(Boolean).join(", ") || "—";
}

export function QueriesScreen({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useProjectQueries(projectId);
  const { data: archivedData } = useProjectArchivedQueries(projectId);
  const { data: dataSources } = useProjectDataSources(projectId);
  const rows = useMemo(() => data ?? [], [data]);
  const archivedRows = useMemo(() => archivedData ?? [], [archivedData]);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [showAddTable, setShowAddTable] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);

  const refreshQueries = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "queries"],
    });
  }, [queryClient, projectId]);

  const restoreMutation = useMutation({
    mutationFn: (id: number) =>
      apiClient.post(`/api/projects/${projectId}/queries/${id}/restore`, {}),
    onSuccess: () => {
      setArchiveError(null);
      refreshQueries();
    },
    onError: (e: Error) => setArchiveError(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete(`/api/projects/${projectId}/queries/${id}`),
    onSuccess: () => {
      setArchiveError(null);
      refreshQueries();
    },
    onError: (e: Error) => setArchiveError(e.message),
  });

  const archiveBusyId =
    restoreMutation.isPending
      ? (restoreMutation.variables ?? null)
      : deleteMutation.isPending
        ? (deleteMutation.variables ?? null)
        : null;

  // ── Deep-link: open a specific query via ?q=<id> ────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    if (q) {
      const id = Number(q);
      if (!Number.isNaN(id)) {
        setDetailId(id);
        setSelectedId(id);
      }
    }
  }, []);

  // ── AI "Generate Query with AI" prompt ──────────────────────────────
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiSuccess, setAiSuccess] = useState<string | null>(null);
  const [aiSuggestions, setAiSuggestions] = useState<string[]>([]);

  const handleGenerateQuery = useCallback(async () => {
    const prompt = aiPrompt.trim();
    if (!prompt || aiLoading) return;
    setAiLoading(true);
    setAiError(null);
    setAiSuccess(null);
    setAiSuggestions([]);
    try {
      const result = await apiClient.post<{
        name?: string;
        status: string;
        message?: string;
        suggested_sources?: string[];
        selected_sources?: { name: string; reason?: string }[];
        repaired?: boolean;
      }>("/api/ai/actions/generate-and-save-query", {
        project_id: Number(projectId),
        prompt,
      });
      if (result.status === "needs_clarification") {
        // Friendly clarification — no raw validation error shown to the user.
        setAiError(
          result.message ??
            "I could not match part of your request to an authorized source.",
        );
        setAiSuggestions(result.suggested_sources ?? []);
        return;
      }
      const verb = result.status === "updated" ? "updated" : "saved";
      const sources = result.selected_sources ?? [];
      let note = `Query ${verb}: ${result.name ?? prompt}`;
      if (sources.length > 0) {
        note += ` — AI selected ${sources
          .map((s) => s.name)
          .join(", ")}`;
      }
      setAiSuccess(note);
      setAiPrompt("");
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "queries"],
      });
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "AI query generation failed");
    } finally {
      setAiLoading(false);
    }
  }, [aiPrompt, aiLoading, projectId, queryClient]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((q) => {
      if (filter === "ai" && !q.ai_generated) return false;
      if (filter === "manual" && q.ai_generated) return false;
      if (filter === "shared" && !q.is_shared) return false;
      if (filter === "private" && q.is_shared) return false;
      if (term && !q.name.toLowerCase().includes(term)) return false;
      return true;
    });
  }, [rows, filter, search]);

  const filteredArchived = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term
      ? archivedRows.filter((q) => q.name.toLowerCase().includes(term))
      : archivedRows;
  }, [archivedRows, search]);

  const handleRestore = useCallback(
    (id: number) => restoreMutation.mutate(id),
    [restoreMutation],
  );
  const handleDelete = useCallback(
    (q: SavedQuery) => {
      if (
        window.confirm(
          `Permanently delete "${q.name}"? This cannot be undone.`,
        )
      ) {
        deleteMutation.mutate(q.id);
      }
    },
    [deleteMutation],
  );

  const selected =
    rows.find((q) => q.id === selectedId) ?? filtered[0] ?? rows[0] ?? null;
  const detailQuery = rows.find((q) => q.id === detailId) ?? null;

  const aiCount = rows.filter((q) => q.ai_generated).length;
  const sharedCount = rows.filter((q) => q.is_shared).length;
  const aiPct = rows.length ? Math.round((aiCount / rows.length) * 100) : 0;

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-queries"
      breadcrumbLabel="Tables"
      actions={
        <Button variant="primary" size="md" onClick={() => setShowAddTable(true)}>
          <IconPlus size={15} />
          New Table
        </Button>
      }
      contextPanel={<QueryPreviewPanel query={detailQuery ?? selected} />}
    >
      {showAddTable && (
        <AddDatasourceModal
          projectId={Number(projectId)}
          onClose={() => setShowAddTable(false)}
          onAdded={() =>
            queryClient.invalidateQueries({
              queryKey: ["project", projectId, "datasources"],
            })
          }
        />
      )}
      {creating ? (
        <QueryBuilderCreate
          projectId={projectId}
          datasources={dataSources ?? []}
          backLabel="Tables"
          onBack={() => setCreating(false)}
          onSaved={() => setCreating(false)}
        />
      ) : detailQuery && editing ? (
        <QueryBuilderEdit
          projectId={projectId}
          query={detailQuery}
          datasources={dataSources ?? []}
          backLabel="Back to results"
          onBack={() => setEditing(false)}
          onSaved={() => setEditing(false)}
        />
      ) : detailQuery ? (
        <QueryResultView
          projectId={projectId}
          query={detailQuery}
          backLabel="Tables"
          onBack={() => setDetailId(null)}
          onEdit={() => setEditing(true)}
        />
      ) : (
      <div className="space-y-4">
        {filter !== "archive" && (
        <div className="rounded-lg border border-brand-100 bg-brand-50/40 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="flex flex-1 items-center gap-2 rounded-md border border-line-secondary bg-bg-primary px-2.5">
              <IconSparkles size={15} className="shrink-0 text-brand-500" />
              <input
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleGenerateQuery();
                }}
                placeholder="Describe the query you want to generate…"
                className="h-9 w-full bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
              />
            </div>
            <Button
              variant="primary"
              onClick={handleGenerateQuery}
              disabled={!aiPrompt.trim() || aiLoading}
            >
              <IconSparkles size={14} />
              {aiLoading ? "Generating…" : "Generate Query with AI"}
            </Button>
          </div>
          {aiError && (
            <p className="mt-2 text-[12px] text-danger">{aiError}</p>
          )}
          {aiSuggestions.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-ink-secondary">
              <span>Related sources:</span>
              {aiSuggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setAiPrompt((p) => `${p} using ${s}`.trim())}
                  className="rounded-full border border-line-secondary px-2 py-0.5 font-medium text-ink-primary hover:bg-bg-secondary"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {aiSuccess && (
            <p className="mt-2 text-[12px] text-success">{aiSuccess}</p>
          )}
        </div>
        )}

        {filter !== "archive" && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Total tables" value={rows.length} />
          <StatTile
            label="AI-generated"
            value={aiCount}
            hint={`${aiPct}% of total`}
          />
          <StatTile
            label="Shared"
            value={sharedCount}
            hint={`${rows.length - sharedCount} private`}
          />
          <StatTile label="Avg run time" value={avgRuntime(rows)} />
        </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <IconSearch
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tables…"
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

        {filter === "archive" ? (
          <ArchiveCard
            rows={filteredArchived}
            error={archiveError}
            busyId={archiveBusyId}
            onRestore={handleRestore}
            onDelete={handleDelete}
          />
        ) : (
        <Card>
          <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
            <span className="text-h3 text-ink-primary">All Tables</span>
            <span className="text-small text-ink-tertiary">
              {filtered.length} total tables
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">Origin</th>
                  <th className="px-4 py-2 font-medium">Owner</th>
                  <th className="px-4 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((q) => {
                  const active = selected?.id === q.id;
                  return (
                    <tr
                      key={q.id}
                      onClick={() => {
                        setSelectedId(q.id);
                        setDetailId(q.id);
                        setEditing(false);
                      }}
                      className={cn(
                        "cursor-pointer border-b border-line-tertiary last:border-0",
                        active
                          ? "bg-brand-50/60"
                          : "hover:bg-bg-secondary",
                      )}
                    >
                      <td className="px-4 py-2.5">
                        <span className="flex items-center gap-1.5">
                          <span
                            className={cn(
                              "font-medium",
                              active ? "text-brand-700" : "text-ink-primary",
                            )}
                          >
                            {q.name}
                          </span>
                          {q.has_outgoing_scope && (
                            <IconTarget
                              size={14}
                              className="shrink-0 text-brand-500"
                              title="This table has an active outgoing scope relationship."
                            />
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {q.source_name ?? q.left_datasource ?? "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={q.ai_generated ? "ai" : "outline"}>
                          {q.origin_label}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {q.owner_name ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 text-ink-tertiary">
                        {timeAgo(q.updated_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!isLoading && filtered.length === 0 && (
              <div className="px-4 py-12 text-center text-small text-ink-tertiary">
                {rows.length === 0
                  ? "No tables yet. Create your first table or generate one with AI."
                  : "No tables match your filters."}
              </div>
            )}
            {isLoading && (
              <div className="px-4 py-12 text-center text-small text-ink-tertiary">
                Loading tables…
              </div>
            )}
          </div>
        </Card>
        )}
      </div>
      )}
    </ProjectShell>
  );
}

function ArchiveCard({
  rows,
  error,
  busyId,
  onRestore,
  onDelete,
}: {
  rows: SavedQuery[];
  error: string | null;
  busyId: number | null;
  onRestore: (id: number) => void;
  onDelete: (q: SavedQuery) => void;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="flex items-center gap-1.5 text-h3 text-ink-primary">
          <IconArchive size={16} className="text-ink-tertiary" />
          Archive
        </span>
        <span className="text-small text-ink-tertiary">
          {rows.length} archived {rows.length === 1 ? "table" : "tables"}
        </span>
      </div>
      {error && (
        <div className="border-b border-danger/30 bg-danger/5 px-4 py-2.5 text-small text-danger">
          {error}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Description</th>
              <th className="px-4 py-2 font-medium">Archived</th>
              <th className="px-4 py-2 font-medium">Owner</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => {
              const busy = busyId === q.id;
              return (
                <tr
                  key={q.id}
                  className="border-b border-line-tertiary last:border-0"
                >
                  <td className="px-4 py-2.5 font-medium text-ink-primary">
                    {q.name}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {q.description || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-ink-tertiary">
                    {archivedDate(q.archived_at)}
                  </td>
                  <td className="px-4 py-2.5 text-ink-secondary">
                    {q.owner_name ?? "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => onRestore(q.id)}
                      >
                        <IconArrowBackUp size={14} />
                        Restore
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={busy}
                        onClick={() => onDelete(q)}
                      >
                        <IconTrash size={14} />
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="px-4 py-12 text-center text-small text-ink-tertiary">
            No archived tables. Archive a table to see it here.
          </div>
        )}
      </div>
    </Card>
  );
}

function QueryPreviewPanel({
  query,
}: {
  query: SavedQuery | null;
}) {
  if (!query) {
    return (
      <ContextPanel title="Query Preview" askPlaceholder="Ask about this query…">
        <div className="px-1 py-8 text-center text-small text-ink-tertiary">
          Select a query to preview its SQL and metadata.
        </div>
      </ContextPanel>
    );
  }
  return (
    <ContextPanel title="Query Preview" askPlaceholder="Ask about this query…">
      <div className="space-y-1">
        <div className="min-w-0 truncate text-caption uppercase tracking-wide text-ink-tertiary">
          {query.name}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {query.ai_generated && <Badge tone="ai">AI generated</Badge>}
          {query.is_shared && <Badge tone="success">Shared</Badge>}
          <span className="text-small text-ink-tertiary">
            {query.left_datasource ?? "—"} · {query.run_count} runs
          </span>
        </div>
      </div>

      {query.sql_text && (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-[#1e1b2e] p-3 font-code text-[12px] leading-relaxed text-[#d6d3e8]">
          {query.sql_text}
        </pre>
      )}

      <ContextSection title="Query Metadata">
        <dl className="space-y-1 text-[13px]">
          <Row label="Source" value={query.left_datasource ?? "—"} />
          <Row label="Tables" value={tablesFor(query)} />
          <Row label="Avg runtime" value={runtimeLabel(query.avg_runtime_ms)} />
          <Row
            label="Last run"
            value={query.last_run_at ? timeAgo(query.last_run_at) : "—"}
          />
          <Row
            label="Created"
            value={`${query.ai_generated ? "AI · " : ""}${timeAgo(query.created_at)}`}
          />
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
