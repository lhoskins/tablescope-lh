"use client";

import { useMemo, useState } from "react";
import { IconSparkles, IconPlus, IconSearch } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectQueries,
  type SavedQuery,
} from "@/lib/ui/use-project-data";

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
  const { data, isLoading } = useProjectQueries(projectId);
  const rows = useMemo(() => data ?? [], [data]);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

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
          <Button variant="secondary">
            <IconSparkles size={14} />
            Generate with AI
          </Button>
          <Button variant="primary">
            <IconPlus size={14} />
            New query
          </Button>
        </>
      }
      contextPanel={<QueryPreviewPanel query={selected} />}
    >
      <div className="space-y-4">
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
                      onClick={() => setSelectedId(q.id)}
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
      </div>
    </ProjectShell>
  );
}

function QueryPreviewPanel({ query }: { query: SavedQuery | null }) {
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
        <div className="text-caption uppercase tracking-wide text-ink-tertiary">
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
        <pre className="overflow-x-auto rounded-lg bg-[#1e1b2e] p-3 font-code text-[12px] leading-relaxed text-[#d6d3e8]">
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
