"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  IconUsers,
  IconTable,
  IconDatabase,
  IconLoader2,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { MembersDialog } from "@/components/tablescope/project/members-dialog";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { ProjectFileDropzone } from "@/components/tablescope/project/project-file-dropzone";
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
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import {
  createConversation,
  getConversation,
  listConversations,
  submitTurn,
  type Conversation,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
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
import { useAccordion } from "@/lib/ui/use-accordion";

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

  const [showMembers, setShowMembers] = useState(false);
  // Single-expand accordion: at most one section open, all may be collapsed.
  const { toggle, isOpen } = useAccordion();
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

  // All tables, most-recently-updated first. The Tables accordion shows the
  // full list (no truncation) when expanded.
  const sortedQueries = [...queryRows].sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );



  const [chatTurns, setChatTurns] = useState<ConversationTurn[]>([]);
  const [chatConversationId, setChatConversationId] = useState<number | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // Resume the single Project Insights conversation for this project so
  // successive asks (including from the AI Assistant) share history.
  const hasResumedRef = useRef(false);
  useEffect(() => {
    if (hasResumedRef.current) return;
    hasResumedRef.current = true;
    let cancelled = false;
    async function resume() {
      try {
        const pid = Number(projectId);
        const convos = await listConversations(pid);
        const match = convos.find(
          (c) => c.title === "Project Insights" && c.project_id === pid,
        );
        if (!match) return;
        const full = await getConversation(match.id);
        if (cancelled) return;
        setChatConversationId(full.id);
        setChatTurns(full.turns);
      } catch {
        // ignore resume errors
      }
    }
    void resume();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const pollConversation = useCallback(async (id: number): Promise<Conversation> => {
    for (let i = 0; i < 60; i++) {
      const data = await getConversation(id);
      const last = data.turns[data.turns.length - 1];
      if (!last || last.status !== "pending") return data;
      await new Promise((r) => setTimeout(r, 1000));
    }
    return getConversation(id);
  }, []);

  const handleAsk = useCallback(
    async (message: string) => {
      setChatBusy(true);
      setChatError(null);
      try {
        if (chatConversationId == null) {
          const created = await createConversation({
            project_id: Number(projectId),
            title: "Project Insights",
            initial_message: message,
          });
          const polled = await pollConversation(created.id);
          setChatConversationId(created.id);
          setChatTurns(polled.turns);
        } else {
          const res = await submitTurn(chatConversationId, { message });
          setChatTurns((prev) => [...prev, res.turn]);
          const polled = await pollConversation(res.conversation_id);
          setChatTurns(polled.turns);
        }
      } catch (err) {
        setChatError(err instanceof Error ? err.message : "Ask failed");
      } finally {
        setChatBusy(false);
      }
    },
    [chatConversationId, projectId, pollConversation],
  );



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
          onAsk={handleAsk}
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



        <HomeAiSuggestions
          projectId={Number(projectId)}
          showAskBox={true}
          onAsk={handleAsk}
        />
        {(chatTurns.length > 0 || chatBusy || chatError) && (
          <div className="space-y-4 rounded-xl border border-line-tertiary bg-bg-primary p-4">
            {chatTurns.map((t, i) => (
              <TurnBubble
                key={t.id}
                turn={t}
                isLast={i === chatTurns.length - 1}
                onFollowUp={handleAsk}
              />
            ))}
            {chatBusy && (
              <div className="flex items-center gap-2 text-small text-ink-tertiary">
                <IconLoader2 size={16} className="animate-spin" />
                TableScope is thinking…
              </div>
            )}
            {chatError && (
              <p className="text-small text-danger">{chatError}</p>
            )}
          </div>
        )}

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

        <OverviewAccordionSection
          type="tables"
          title="Tables"
          subtitle="Saved and AI-generated tables in this project"
          count={queryRows.length}
          open={isOpen("tables")}
          onToggle={() => toggle("tables")}
        >
          {sortedQueries.length === 0 ? (
            <div className="px-4 py-10 text-center text-small text-ink-tertiary">
              No tables yet.
            </div>
          ) : (
            <div className="max-h-[32rem] overflow-y-auto">
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
                  {sortedQueries.map((q) => (
                    <QueryRow
                      key={q.id}
                      q={q}
                      onClick={() => router.push(`/projects/${projectId}/queries?q=${q.id}`)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </OverviewAccordionSection>

        <OverviewAccordionSection
          type="sources"
          title="Data Sources"
          subtitle="Connected databases, files, and SaaS objects"
          count={sourceRows.length}
          open={isOpen("sources")}
          onToggle={() => toggle("sources")}
        >
          {sourceRows.length === 0 ? (
            <div className="px-4 py-10 text-center text-small text-ink-tertiary">
              No data sources connected yet.
            </div>
          ) : (
            <>
              <div className="max-h-[32rem] overflow-y-auto">
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
                  {sourceRows.map((s) => (
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
              </div>
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
        </OverviewAccordionSection>

        <section className="space-y-2 rounded-xl border border-line-tertiary bg-bg-primary p-4">
          <div>
            <h3 className="text-h3 text-ink-primary">Add a data source</h3>
            <p className="text-small text-ink-tertiary">
              Upload a CSV or Excel file to this project; you will continue in
              the Data Source Builder.
            </p>
          </div>
          <ProjectFileDropzone
            project={project ?? undefined}
            tenantName={tenant.name}
          />
        </section>
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

const OVERVIEW_SECTION_STYLES = {
  tables: {
    background: "#F8FBFF",
    border: "#D7E8FF",
    accent: "#1E6FD9",
    Icon: IconTable,
  },
  sources: {
    background: "#F7FFFB",
    border: "#D4F0E2",
    accent: "#2EA66F",
    Icon: IconDatabase,
  },
} as const;

function OverviewAccordionSection({
  type,
  title,
  subtitle,
  count,
  open,
  onToggle,
  children,
}: {
  type: "tables" | "sources";
  title: string;
  subtitle: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  const style = OVERVIEW_SECTION_STYLES[type];
  const Icon = style.Icon;
  return (
    <div
      className="overflow-hidden rounded-xl border"
      style={{ background: style.background, borderColor: style.border }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left"
      >
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
          style={{ background: `${style.accent}1A`, color: style.accent }}
        >
          <Icon size={18} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span
              className="text-h3 font-semibold"
              style={{ color: style.accent }}
            >
              {title}
            </span>
            <span
              className="rounded-full px-2 py-0.5 text-caption font-medium tabular-nums"
              style={{ background: `${style.accent}1A`, color: style.accent }}
            >
              {count}
            </span>
          </span>
          <span className="block text-small text-ink-tertiary">{subtitle}</span>
        </span>
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border text-body font-semibold"
          style={{ borderColor: style.border, color: style.accent }}
          aria-hidden
        >
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <div
          className="border-t bg-bg-primary"
          style={{ borderColor: style.border }}
        >
          {children}
        </div>
      )}
    </div>
  );
}
