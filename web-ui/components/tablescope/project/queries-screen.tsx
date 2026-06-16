"use client";

import { useCallback, useMemo, useState } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { IconSparkles, IconPlus, IconSearch, IconTable } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { ScopesTab } from "@/components/scopes/ScopesTab";
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
  useProjectDataSources,
  type SavedQuery,
} from "@/lib/ui/use-project-data";
import {
  QueryResultView,
  QueryBuilderEdit,
  QueryBuilderCreate,
} from "@/components/tablescope/project/detail-views";

type ProjectScoping = { scoping_enabled?: boolean };

type Filter = "all" | "ai" | "manual" | "shared" | "private";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ai", label: "AI-generated" },
  { key: "manual", label: "Manual" },
  { key: "shared", label: "Shared" },
  { key: "private", label: "Private" },
];

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
  const { data: dataSources } = useProjectDataSources(projectId);
  const rows = useMemo(() => data ?? [], [data]);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"queries" | "scopes">("queries");
  const [showAddTable, setShowAddTable] = useState(false);

  // ── AI "Generate Query with AI" prompt ──────────────────────────────
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiSuccess, setAiSuccess] = useState<string | null>(null);

  const handleGenerateQuery = useCallback(async () => {
    const prompt = aiPrompt.trim();
    if (!prompt || aiLoading) return;
    setAiLoading(true);
    setAiError(null);
    setAiSuccess(null);
    try {
      const result = await apiClient.post<{ name: string; status: string }>(
        "/api/ai/actions/generate-and-save-query",
        { project_id: Number(projectId), prompt },
      );
      const verb = result.status === "updated" ? "updated" : "saved";
      setAiSuccess(`Query ${verb}: ${result.name}`);
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

  // ── Scope toggle (project scoping) ──────────────────────────────────
  const { data: projectInfo } = useQuery<ProjectScoping>({
    queryKey: ["project", projectId, "info"],
    queryFn: () => apiClient.get<ProjectScoping>(`/api/projects/${projectId}`),
  });
  const scopingEnabled = projectInfo?.scoping_enabled ?? false;
  const toggleScoping = useMutation({
    mutationFn: async (enabled: boolean) => {
      const result = await apiClient.put(`/api/projects/${projectId}`, {
        scoping_enabled: enabled,
      });
      if (enabled) {
        try {
          await apiClient.post(`/api/ai/project/scope-map/auto-create`, {
            project_id: Number(projectId),
          });
        } catch {
          /* scoping enabled even if auto-create finds nothing */
        }
      }
      return result;
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project", projectId, "info"] }),
  });

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
      breadcrumbLabel="Queries"
      actions={
        <>
          <button
            type="button"
            onClick={() => toggleScoping.mutate(!scopingEnabled)}
            disabled={toggleScoping.isPending}
            className="flex items-center gap-2 rounded-md border border-line-secondary px-2.5 py-1.5 text-[12px] font-medium text-ink-secondary hover:bg-bg-secondary disabled:opacity-50"
            title={scopingEnabled ? "Click to disable scoping" : "Click to enable scoping"}
          >
            <span
              className={cn(
                "relative inline-flex h-4 w-7 items-center rounded-full transition-colors",
                scopingEnabled ? "bg-brand-500" : "bg-line-secondary",
              )}
            >
              <span
                className="inline-block h-3 w-3 rounded-full bg-white shadow transition-transform"
                style={{ transform: scopingEnabled ? "translateX(14px)" : "translateX(2px)" }}
              />
            </span>
            {toggleScoping.isPending
              ? "Updating…"
              : scopingEnabled
                ? "Scopes On"
                : "Scopes Off"}
          </button>
          <Button variant="secondary" onClick={() => setShowAddTable(true)}>
            <IconTable size={14} />
            New Table
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              setDetailId(null);
              setEditing(false);
              setCreating(true);
            }}
          >
            <IconPlus size={14} />
            New query
          </Button>
        </>
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
          backLabel="Queries"
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
          backLabel="Queries"
          onBack={() => setDetailId(null)}
          onEdit={() => setEditing(true)}
        />
      ) : (
      <div className="space-y-4">
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
          {aiSuccess && (
            <p className="mt-2 text-[12px] text-success">{aiSuccess}</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Total queries" value={rows.length} />
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

        <div className="flex items-center gap-1 border-b border-line-tertiary">
          {([
            { key: "queries", label: "All Queries" },
            { key: "scopes", label: "Scopes" },
          ] as const).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium",
                tab === t.key
                  ? "border-brand-500 text-brand-700"
                  : "border-transparent text-ink-secondary hover:text-ink-primary",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "scopes" ? (
          <ScopesTab projectId={Number(projectId)} />
        ) : (
        <>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <IconSearch
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search queries…"
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
            <span className="text-h3 text-ink-primary">All Queries</span>
            <span className="text-small text-ink-tertiary">
              {filtered.length} total
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">Origin</th>
                  <th className="px-4 py-2 font-medium">Visibility</th>
                  <th className="px-4 py-2 font-medium">Runs</th>
                  <th className="px-4 py-2 font-medium">Avg time</th>
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
                        <span
                          className={cn(
                            "font-medium",
                            active ? "text-brand-700" : "text-ink-primary",
                          )}
                        >
                          {q.name}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {q.left_datasource ?? "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={q.ai_generated ? "ai" : "outline"}>
                          {q.ai_generated ? "AI" : "Manual"}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={q.is_shared ? "success" : "neutral"}>
                          {q.is_shared ? "Shared" : "Private"}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {q.run_count}
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {runtimeLabel(q.avg_runtime_ms)}
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
                  ? "No queries yet. Create your first query or generate one with AI."
                  : "No queries match your filters."}
              </div>
            )}
            {isLoading && (
              <div className="px-4 py-12 text-center text-small text-ink-tertiary">
                Loading queries…
              </div>
            )}
          </div>
        </Card>
        </>
        )}
      </div>
      )}
    </ProjectShell>
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
