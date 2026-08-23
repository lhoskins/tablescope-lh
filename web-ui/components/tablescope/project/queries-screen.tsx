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
  IconTable,
  IconShare,
  IconClock,
  IconCode,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { AIQueryDesigner } from "@/components/tablescope/project/ai-query-designer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToasts, ToastViewport } from "@/components/ui/toast";
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
import { StatBar, type StatItem } from "./overview-screen/stat-bar";
import { Filter } from "./queries-screen/filter";
import { FILTERS } from "./queries-screen/filters";
import { avgRuntime } from "./queries-screen/avg-runtime";
import { ArchiveCard } from "./queries-screen/archive-card";



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

  // ── "Create Query with AI" dialog ────────────────────────────────────
  // Mirrors the AI Dashboard Designer's flow: a parameterized dialog
  // (specific columns/metrics, period, dimension) that generates, shows the
  // chart/table/SQL preview, and only persists on explicit Save -- instead
  // of the single-line prompt bar this replaced, which offered none of the
  // dashboard designer's structured "Creation context" and only a plain
  // free-text box.
  const [aiDesignerOpen, setAiDesignerOpen] = useState(false);
  const { toasts, push, dismiss } = useToasts();

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
  const listMode = !creating && !editing && !detailQuery;

  const aiCount = rows.filter((q) => q.ai_generated).length;
  const sharedCount = rows.filter((q) => q.is_shared).length;
  const aiPct = rows.length ? Math.round((aiCount / rows.length) * 100) : 0;

  const statItems: StatItem[] = [
    {
      key: "total",
      icon: IconTable,
      iconClass: "bg-brand-50 text-brand-700",
      value: rows.length,
      label: "Total tables",
    },
    {
      key: "ai",
      icon: IconSparkles,
      iconClass: "bg-ai-bg text-ai",
      value: aiCount,
      label: "AI-generated",
    },
    {
      key: "shared",
      icon: IconShare,
      iconClass: "bg-success-bg text-success",
      value: sharedCount,
      label: "Shared",
    },
    {
      key: "runtime",
      icon: IconClock,
      iconClass: "bg-warning-bg text-warning",
      value: avgRuntime(rows),
      label: "Avg run time",
    },
  ];

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-queries"
      breadcrumbLabel="Tables"
      showProjectHeader={listMode}
      workspaceItem={
        detailQuery
          ? {
              type: "table",
              id: String(detailQuery.id),
              numericId: detailQuery.id,
              label: detailQuery.name,
              href: `/projects/${projectId}/queries?q=${detailQuery.id}`,
            }
          : null
      }
      headerActions={
        listMode ? (
          <>
            <Button variant="secondary" size="md" onClick={() => setCreating(true)}>
              <IconCode size={15} />
              Query Builder (legacy)
            </Button>
            <Button variant="primary" size="md" onClick={() => setAiDesignerOpen(true)}>
              <IconSparkles size={15} />
              Create Query with AI
            </Button>
            <Button variant="primary" size="md" onClick={() => setShowAddTable(true)}>
              <IconPlus size={15} />
              New Table
            </Button>
          </>
        ) : undefined
      }
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
        {filter !== "archive" && <StatBar items={statItems} />}

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
      <AIQueryDesigner
        open={aiDesignerOpen}
        projectId={projectId}
        onClose={() => setAiDesignerOpen(false)}
        onSaved={() => refreshQueries()}
        notify={push}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}
