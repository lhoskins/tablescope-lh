"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  IconArrowUp,
  IconUsers,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { MembersDialog } from "@/components/tablescope/project/members-dialog";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import {
  DataSourceResultView,
} from "@/components/tablescope/project/detail-views";
import {
  ContextPanel,
  ContextSection,
  IsolationCard,
} from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectShell,
  useProjectQueries,
  useProjectDataSources,
  useProjectDashboards,
  useProjectMembers,
  useProjectActivity,
  useProjectGraph,
  type SavedQuery,
  type DataSource,
} from "@/lib/ui/use-project-data";

const QUICK_PROMPTS = [
  "Supplier delay trends",
  "Top suppliers by spend",
  "Quality trends",
  "Compare by region",
];

function isDatabase(s: DataSource): boolean {
  return s.sourceType === "database_table";
}
function isSaas(s: DataSource): boolean {
  return s.sourceType === "saas_object";
}
function sourceTypeLabel(s: DataSource): string {
  if (isDatabase(s)) return s.dbType ?? "Database";
  if (isSaas(s)) return s.connectorType ?? "SaaS API";
  return (s.sourceType || "File").toUpperCase();
}

export function OverviewScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { project, tenant, user } = useProjectShell(projectId);
  const { data: queries } = useProjectQueries(projectId);
  const { data: sources } = useProjectDataSources(projectId);
  const { data: dashboards } = useProjectDashboards(projectId);
  const { data: members } = useProjectMembers(projectId);
  const { data: activity } = useProjectActivity(projectId);
  const { data: graph } = useProjectGraph(projectId);

  const [ask, setAsk] = useState("");
  const [showMembers, setShowMembers] = useState(false);
  const [openTables, setOpenTables] = useState(false);
  const [openSources, setOpenSources] = useState(false);
  const { toasts, push, dismiss } = useToasts();
  const [detail, setDetail] = useState<
    { kind: "query"; id: number } | { kind: "source"; name: string } | null
  >(null);

  const queryRows = useMemo(() => queries ?? [], [queries]);
  const sourceRows = useMemo(
    () => (sources ?? []).filter((s) => !s.archived),
    [sources],
  );
  const dashboardRows = useMemo(() => dashboards ?? [], [dashboards]);
  const tableNodes = useMemo(
    () =>
      (graph?.nodes ?? []).filter((n) =>
        ["table", "data_source", "datasource"].some((t) =>
          n.type.toLowerCase().includes(t),
        ),
      ),
    [graph],
  );
  const edges = graph?.edges ?? [];
  const aiActions = (activity?.events ?? []).filter(
    (e) => e.category === "ai",
  );

  const connectedSources = sourceRows.filter((s) => !isSaas(s)).length;
  const publishedDashboards = dashboardRows.filter(
    (d) => d.status === "published",
  ).length;
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const newQueriesThisWeek = queryRows.filter(
    (q) => new Date(q.created_at).getTime() >= weekAgo,
  ).length;
  const memberCount = (members ?? []).filter((m) => m.is_active).length;


  const detailSource =
    detail?.kind === "source"
      ? (sourceRows.find((s) => (s.viewName || s.fileName) === detail.name) ??
        null)
      : null;

  const recentQueries = [...queryRows]
    .sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
    .slice(0, 4);



  const goAsk = (prompt: string) => {
    const q = prompt.trim();
    router.push(
      `/projects/${projectId}/ai${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    );
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="overview"
      breadcrumbLabel="Overview"
      actions={
        <>
          <ShareToggle
            projectId={projectId}
            shared={project?.visibility === "shared"}
            onToast={push}
          />
          <Button variant="secondary" onClick={() => setShowMembers(true)}>
            <IconUsers size={14} />
            Members
          </Button>
        </>
      }
      contextPanel={
        <ContextPanel
          title="AI Context"
          askPlaceholder="Ask about this project…"
          onAsk={goAsk}
        >
          <IsolationCard
            tenant={tenant.name}
            project={project?.name ?? "Project"}
            user={user.name || user.email || "You"}
          />

          {aiActions[0] ? (
            <div className="rounded-lg border-l-2 border-brand-500 bg-brand-50/60 p-3">
              <p className="text-[13px] leading-relaxed text-ink-primary">
                {aiActions[0].title}
              </p>
              <p className="mt-1.5 text-small text-brand-700">
                AI insight · {timeAgo(aiActions[0].ts)} · all logged
              </p>
            </div>
          ) : null}

          <ContextSection title="Relationship Chain">
            {edges.length === 0 ? (
              <p className="text-small text-ink-tertiary">
                No relationships mapped yet.
              </p>
            ) : (
              <ul className="space-y-1 text-[13px] text-ink-secondary">
                {edges.slice(0, 4).map((e) => {
                  const byId = new Map(
                    (graph?.nodes ?? []).map((n) => [n.id, n.label]),
                  );
                  return (
                    <li key={e.id} className="truncate">
                      <span className="text-ink-primary">
                        {byId.get(e.source)}
                      </span>{" "}
                      <span className="text-ink-tertiary">{e.type} →</span>{" "}
                      <span className="text-ink-primary">
                        {byId.get(e.target)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </ContextSection>

          <ContextSection title="In-Scope Tables">
            {tableNodes.length === 0 ? (
              <p className="text-small text-ink-tertiary">
                {sourceRows.length} sources connected.
              </p>
            ) : (
              <ul className="space-y-1 text-[13px] text-ink-secondary">
                {tableNodes.slice(0, 3).map((n) => (
                  <li key={n.id} className="truncate">
                    {n.label}
                  </li>
                ))}
                {tableNodes.length > 3 && (
                  <li className="text-ink-tertiary">
                    +{tableNodes.length - 3} more in scope
                  </li>
                )}
              </ul>
            )}
          </ContextSection>

          <ContextSection title="Recent AI Actions">
            {aiActions.length === 0 ? (
              <p className="text-small text-ink-tertiary">
                No AI actions yet.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {aiActions.slice(0, 4).map((e) => (
                  <li
                    key={e.id}
                    className="flex items-center justify-between gap-2 text-[13px]"
                  >
                    <span className="min-w-0 truncate text-ink-secondary">
                      {e.title}
                    </span>
                    <span className="shrink-0 text-small text-ink-tertiary">
                      {timeAgo(e.ts)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </ContextSection>
        </ContextPanel>
      }
    >
      {detailSource ? (
        <DataSourceResultView
          projectId={projectId}
          source={detailSource}
          backLabel="Overview"
          onBack={() => setDetail(null)}
        />
      ) : (
      <div className="space-y-4">
        <header className="flex items-start gap-3">
          <span
            className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg"
            style={{ backgroundColor: project?.accent ?? "var(--brand-50)" }}
          />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-h1 text-ink-primary">
                {project?.name ?? "Project"}
              </h1>
              <Badge tone="success">+ AI Ready</Badge>
            </div>
            <p className="mt-0.5 text-small text-ink-tertiary">
              {project?.visibility === "shared" ? "Shared" : "Private"} project
              {memberCount > 0 && ` · ${memberCount} member${memberCount === 1 ? "" : "s"}`}
              {project?.updatedLabel && ` · Updated ${project.updatedLabel}`}
            </p>
          </div>
        </header>



        <Card className="space-y-3 p-4">
          <div className="flex items-center gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2.5">
            <input
              value={ask}
              onChange={(e) => setAsk(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") goAsk(ask);
              }}
              placeholder="Ask about your data, documents, or dashboards…"
              className="min-w-0 flex-1 bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
            />
            <button
              type="button"
              onClick={() => goAsk(ask)}
              aria-label="Ask AI"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-brand text-brand-fg hover:bg-brand-700"
            >
              <IconArrowUp size={15} />
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {QUICK_PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => goAsk(p)}
                className="rounded-full border border-line-secondary bg-bg-primary px-3 py-1 text-[12px] text-ink-secondary hover:border-brand-500 hover:bg-brand-50/40"
              >
                {p}
              </button>
            ))}
          </div>
        </Card>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile
            label="Data Sources"
            value={sourceRows.length}
            hint={`${connectedSources} connected`}
          />
          <StatTile
            label="Tables"
            value={project?.queryCount ?? queryRows.length}
            hint={
              newQueriesThisWeek > 0
                ? `↑ ${newQueriesThisWeek} this week`
                : undefined
            }
          />
          <StatTile
            label="Documents"
            value={project?.documentCount ?? 0}
            hint={`${edges.length} relationships`}
          />
          <StatTile
            label="Dashboards"
            value={project?.dashboardCount ?? dashboardRows.length}
            hint={`${publishedDashboards} published`}
          />
          <StatTile
            label="AI Actions"
            value={activity?.stats.ai_actions ?? aiActions.length}
            hint="All audited"
            hintTone="success"
          />
        </div>

        <Card className="overflow-hidden">
          <button
            type="button"
            onClick={() => setOpenTables((v) => !v)}
            aria-expanded={openTables}
            className="flex w-full items-center gap-2 border-b border-line-tertiary px-4 py-3 text-left hover:bg-bg-secondary"
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center text-body font-semibold text-ink-tertiary">
              {openTables ? "−" : "+"}
            </span>
            <span className="text-h3 text-ink-primary">
              Tables ({queryRows.length})
            </span>
          </button>
          {!openTables ? null : recentQueries.length === 0 ? (
            <div className="px-4 py-10 text-center text-small text-ink-tertiary">
              No tables yet.
            </div>
          ) : (
            <>
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="border-b border-line-tertiary text-caption uppercase tracking-wide text-ink-tertiary">
                    <Th>Name</Th>
                    <Th>Source</Th>
                    <Th>Origin</Th>
                    <Th>Visibility</Th>
                    <Th className="text-right">Updated</Th>
                  </tr>
                </thead>
                <tbody>
                  {recentQueries.map((q) => (
                    <QueryRow
                      key={q.id}
                      q={q}
                      onClick={() => router.push(`/projects/${projectId}/queries?q=${q.id}`)}
                    />
                  ))}
                </tbody>
              </table>
              <div className="flex justify-end border-t border-line-tertiary px-4 py-2.5">
                <button
                  type="button"
                  onClick={() => router.push(`/projects/${projectId}/queries`)}
                  className="text-small font-medium text-brand-700 hover:underline"
                >
                  View all
                </button>
              </div>
            </>
          )}
        </Card>

        <Card className="overflow-hidden">
          <button
            type="button"
            onClick={() => setOpenSources((v) => !v)}
            aria-expanded={openSources}
            className="flex w-full items-center gap-2 border-b border-line-tertiary px-4 py-3 text-left hover:bg-bg-secondary"
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center text-body font-semibold text-ink-tertiary">
              {openSources ? "−" : "+"}
            </span>
            <span className="text-h3 text-ink-primary">
              Data Sources ({sourceRows.length})
            </span>
          </button>
          {!openSources ? null : sourceRows.length === 0 ? (
            <div className="px-4 py-10 text-center text-small text-ink-tertiary">
              No data sources connected yet.
            </div>
          ) : (
            <>
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="border-b border-line-tertiary text-caption uppercase tracking-wide text-ink-tertiary">
                    <Th>Name</Th>
                    <Th>Type</Th>
                    <Th className="text-right">Tables</Th>
                    <Th>Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {sourceRows.slice(0, 5).map((s) => (
                    <tr
                      key={s.viewName || s.fileName}
                      onClick={() =>
                        setDetail({
                          kind: "source",
                          name: s.viewName || s.fileName,
                        })
                      }
                      className="cursor-pointer border-b border-line-tertiary last:border-0 hover:bg-bg-secondary"
                    >
                      <td className="px-4 py-2.5 font-medium text-ink-primary">
                        {s.viewName || s.fileName}
                      </td>
                      <td className="px-4 py-2.5 text-ink-secondary">
                        {sourceTypeLabel(s)}
                      </td>
                      <td className="px-4 py-2.5 text-right text-ink-secondary">
                        {s.columnTypes?.length ?? "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={isSaas(s) ? "warning" : "success"}>
                          {isSaas(s) ? "Pending auth" : "Connected"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex justify-end border-t border-line-tertiary px-4 py-2.5">
                <button
                  type="button"
                  onClick={() => router.push(`/projects/${projectId}/data-sources`)}
                  className="text-small font-medium text-brand-700 hover:underline"
                >
                  Connect new
                </button>
              </div>
            </>
          )}
        </Card>
      </div>
      )}
      <MembersDialog
        open={showMembers}
        projectId={projectId}
        onClose={() => setShowMembers(false)}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}

function QueryRow({ q, onClick }: { q: SavedQuery; onClick?: () => void }) {
  const source = [q.left_datasource, q.right_datasource]
    .filter(Boolean)
    .join(", ");
  return (
    <tr
      onClick={onClick}
      className="cursor-pointer border-b border-line-tertiary last:border-0 hover:bg-bg-secondary"
    >
      <td className="px-4 py-2.5 font-medium text-ink-primary">{q.name}</td>
      <td className="px-4 py-2.5 text-ink-secondary">{source || "—"}</td>
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
      <td className="px-4 py-2.5 text-right text-ink-tertiary">
        {timeAgo(q.updated_at)}
      </td>
    </tr>
  );
}

function Th({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <th className={cn("px-4 py-2 font-medium", className)}>{children}</th>;
}
