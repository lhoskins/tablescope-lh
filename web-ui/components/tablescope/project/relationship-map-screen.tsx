"use client";

import { useMemo, useState } from "react";
import {
  IconDatabase,
  IconCode,
  IconFileText,
  IconLayoutDashboard,
  IconFilter,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import {
  useProjectGraph,
  type GraphId,
  type GraphNode,
  type GraphEdge,
} from "@/lib/ui/use-project-data";

type Column = "table" | "query" | "document" | "dashboard";

const COLUMNS: { key: Column; label: string; icon: typeof IconDatabase }[] = [
  { key: "table", label: "Data Sources", icon: IconDatabase },
  { key: "query", label: "Queries", icon: IconCode },
  { key: "document", label: "Documents", icon: IconFileText },
  { key: "dashboard", label: "Dashboards", icon: IconLayoutDashboard },
];

function columnFor(type: string): Column | null {
  const t = type.toLowerCase();
  if (t.includes("table") || t.includes("source") || t.includes("datasource"))
    return "table";
  if (t.includes("query")) return "query";
  if (t.includes("dashboard")) return "dashboard";
  if (t.includes("document") || t.includes("asset") || t.includes("family"))
    return "document";
  return null;
}

export function RelationshipMapScreen({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectGraph(projectId);
  const nodes = useMemo(() => data?.nodes ?? [], [data]);
  const edges = useMemo(() => data?.edges ?? [], [data]);
  const [filter, setFilter] = useState<Column | "all">("all");
  const [selectedId, setSelectedId] = useState<GraphId | null>(null);

  const byColumn = useMemo(() => {
    const map: Record<Column, GraphNode[]> = {
      table: [],
      query: [],
      document: [],
      dashboard: [],
    };
    for (const n of nodes) {
      const col = columnFor(n.type);
      if (col) map[col].push(n);
    }
    return map;
  }, [nodes]);

  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  const visibleColumns = COLUMNS.filter(
    (c) => filter === "all" || filter === c.key,
  );

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-relationship-map"
      breadcrumbLabel="Relationship Map"
      actions={
        <>
          <Button variant="secondary">
            <IconFilter size={14} />
            Filter
          </Button>
          <Button variant="secondary">Export</Button>
        </>
      }
      contextPanel={
        <SelectedNodePanel selected={selected} nodes={nodes} edges={edges} />
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {(["all", ...COLUMNS.map((c) => c.key)] as const).map((key) => {
            const label =
              key === "all"
                ? "All"
                : COLUMNS.find((c) => c.key === key)?.label ?? key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setFilter(key)}
                className={cn(
                  "h-8 rounded-md border px-3 text-[12px] font-medium",
                  filter === key
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-line-secondary bg-bg-primary text-ink-secondary hover:bg-bg-secondary",
                )}
              >
                {label}
              </button>
            );
          })}
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-small text-ink-tertiary">
            Loading relationship graph…
          </div>
        ) : nodes.length === 0 ? (
          <Card className="px-4 py-16 text-center text-small text-ink-tertiary">
            No relationships detected yet. As the AI indexes your data sources
            and documents, it maps how they connect here.
          </Card>
        ) : (
          <div
            className="grid gap-4"
            style={{
              gridTemplateColumns: `repeat(${visibleColumns.length}, minmax(0, 1fr))`,
            }}
          >
            {visibleColumns.map((col) => {
              const Icon = col.icon;
              return (
                <div key={col.key} className="space-y-2">
                  <div className="flex items-center gap-1.5 text-caption uppercase tracking-wide text-ink-tertiary">
                    <Icon size={13} /> {col.label}
                    <span className="text-ink-tertiary">
                      ({byColumn[col.key].length})
                    </span>
                  </div>
                  {byColumn[col.key].map((n) => {
                    const active = n.id === selectedId;
                    return (
                      <button
                        key={n.id}
                        type="button"
                        onClick={() => setSelectedId(n.id)}
                        className={cn(
                          "w-full rounded-lg border bg-bg-primary px-3 py-2.5 text-left",
                          active
                            ? "border-brand-500 ring-1 ring-brand-500"
                            : "border-line-tertiary hover:border-line-secondary hover:bg-bg-secondary",
                        )}
                      >
                        <div className="truncate text-[13px] font-medium text-ink-primary">
                          {n.label}
                        </div>
                        <div className="mt-0.5 text-small text-ink-tertiary">
                          {n.type}
                        </div>
                      </button>
                    );
                  })}
                  {byColumn[col.key].length === 0 && (
                    <div className="rounded-lg border border-dashed border-line-tertiary px-3 py-4 text-center text-small text-ink-tertiary">
                      None
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {nodes.length > 0 && (
          <Card>
            <div className="border-b border-line-tertiary px-4 py-3 text-h3 text-ink-primary">
              Graph Statistics
            </div>
            <div className="grid grid-cols-2 gap-4 px-4 py-4 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Total nodes" value={nodes.length} />
              {COLUMNS.map((c) => (
                <Stat
                  key={c.key}
                  label={c.label}
                  value={byColumn[c.key].length}
                />
              ))}
              <Stat label="Relationships" value={edges.length} />
            </div>
          </Card>
        )}
      </div>
    </ProjectShell>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-caption uppercase tracking-wide text-ink-tertiary">
        {label}
      </div>
      <div className="mt-0.5 text-h1 text-ink-primary">{value}</div>
    </div>
  );
}

function SelectedNodePanel({
  selected,
  nodes,
  edges,
  collapsible = true,
}: {
  selected: GraphNode | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  collapsible?: boolean;
}) {
  if (!selected) {
    return (
      <ContextPanel title="Selected Node" askPlaceholder="Ask about this node…" collapsible={collapsible}>
        <div className="px-1 py-8 text-center text-small text-ink-tertiary">
          Select a node to see its relationships.
        </div>
      </ContextPanel>
    );
  }
  const labelById = new Map(nodes.map((n) => [n.id, n]));
  const related = edges
    .filter((e) => e.source === selected.id || e.target === selected.id)
    .map((e) => {
      const otherId = e.source === selected.id ? e.target : e.source;
      return { edge: e, other: labelById.get(otherId) };
    })
    .filter((r) => r.other);

  return (
    <ContextPanel title="Selected Node" askPlaceholder="Ask about this node…">
      <div className="space-y-1">
        <div className="text-h3 text-ink-primary">{selected.label}</div>
        <Badge tone="neutral">{selected.type}</Badge>
      </div>

      <ContextSection title={`Relationships (${related.length})`}>
        {related.length === 0 ? (
          <div className="text-small text-ink-tertiary">
            No connections recorded.
          </div>
        ) : (
          <ul className="space-y-1.5 text-[13px]">
            {related.map(({ edge, other }) => (
              <li
                key={edge.id}
                className="flex items-center justify-between gap-2"
              >
                <span className="min-w-0 truncate text-ink-primary">
                  {other?.label}
                </span>
                <Badge tone="brand" className="shrink-0">
                  {edge.type}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </ContextSection>
    </ContextPanel>
  );
}
