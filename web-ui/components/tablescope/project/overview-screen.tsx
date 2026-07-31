"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconUsers,
  IconLoader2,
  IconDatabase,
  IconCode,
  IconFileText,
  IconLayoutDashboard,
  IconSparkles,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { MembersDialog } from "@/components/tablescope/project/members-dialog";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { ContextPanel, ContextSection, IsolationCard } from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";
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
import { projectInsightApi, type ProjectInsight, type ProjectInsightCard } from "@/lib/api/project-insight";
import { cn } from "@/lib/cn";
import { timeAgo, aiStatusLabel, aiStatusTone } from "@/lib/ui/format";
import type { AiStatus, ProjectSummary } from "@/lib/ui/types";
import {
  useProjectShell,
  useProjectQueries,
  useProjectDataSources,
  useProjectDashboards,
  useProjectMembers,
  useProjectActivity,
  useProjectGraph,
  type DataSource,
  type ActivityEvent,
} from "@/lib/ui/use-project-data";

function isDatabase(s: DataSource): boolean {
  return s.sourceType === "database_table";
}
function isSaas(s: DataSource): boolean {
  return s.sourceType === "saas_object";
}

function severityTone(severity: string) {
  switch (severity) {
    case "critical":
    case "urgent":
      return "danger" as const;
    case "warning":
    case "watch":
      return "warning" as const;
    case "opportunity":
    case "recommendation":
      return "success" as const;
    case "trend":
    case "informational":
    default:
      return "neutral" as const;
  }
}

function insightCategory(insightType: string) {
  const map: Record<string, string> = {
    risk: "Risk",
    trend: "Trend",
    opportunity: "Opportunity",
    analysis: "Analysis",
  };
  return map[insightType] || insightType;
}

const PROJECT_INSIGHTS_TITLE = "Project Insights";
const PROJECT_INSIGHTS_SURFACE = "project_insights";

async function pollConversation(id: number): Promise<Conversation> {
  for (let i = 0; i < 60; i++) {
    const data = await getConversation(id);
    const last = data.turns[data.turns.length - 1];
    if (!last || last.status !== "pending") return data;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return getConversation(id);
}

export function OverviewScreen({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { project, tenant, user } = useProjectShell(projectId);
  const { data: queries } = useProjectQueries(projectId);
  const { data: sources } = useProjectDataSources(projectId);
  const { data: dashboards } = useProjectDashboards(projectId);
  const { data: members } = useProjectMembers(projectId);
  const { data: activity } = useProjectActivity(projectId);
  const { data: graph } = useProjectGraph(projectId);

  const [showMembers, setShowMembers] = useState(false);
  const { toasts, push, dismiss } = useToasts();

  // ── Ask Anything: one shared Project Insights conversation per project.
  const [chatTurns, setChatTurns] = useState<ConversationTurn[]>([]);
  const [chatConversationId, setChatConversationId] = useState<number | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const hasResumedRef = useRef(false);

  useEffect(() => {
    if (hasResumedRef.current) return;
    hasResumedRef.current = true;
    let cancelled = false;
    async function resume() {
      try {
        const pid = Number(projectId);
        const convos = await listConversations(pid);
        const match =
          convos.find((c) => c.surface === PROJECT_INSIGHTS_SURFACE && c.project_id === pid) ??
          convos.find((c) => c.title === PROJECT_INSIGHTS_TITLE && c.project_id === pid);
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

  const handleAsk = useCallback(
    async (message: string) => {
      setChatBusy(true);
      setChatError(null);
      try {
        if (chatConversationId == null) {
          const created = await createConversation({
            project_id: Number(projectId),
            title: PROJECT_INSIGHTS_TITLE,
            surface: PROJECT_INSIGHTS_SURFACE,
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
    [chatConversationId, projectId],
  );

  // ── Recent insights from the latest Project Insight snapshot.
  const { data: projectInsight } = useQuery<ProjectInsight>({
    queryKey: ["project", projectId, "insight", "recent"],
    queryFn: () => projectInsightApi.get(projectId),
    enabled: Boolean(projectId),
    staleTime: 5 * 60 * 1000,
  });

  const recentInsights = useMemo(() => {
    if (!projectInsight) return [];
    const all: Array<ProjectInsightCard & { category: string }> = [
      ...projectInsight.risks.map((c) => ({ ...c, category: "risk" })),
      ...projectInsight.trends.map((c) => ({ ...c, category: "trend" })),
      ...projectInsight.opportunities.map((c) => ({ ...c, category: "opportunity" })),
      ...projectInsight.analysis.map((c) => ({ ...c, category: "analysis" })),
    ];
    return all
      .filter((c) => c.title?.trim())
      .sort((a, b) => {
        const ta = new Date(a.executedAt ?? projectInsight.generatedAt).getTime();
        const tb = new Date(b.executedAt ?? projectInsight.generatedAt).getTime();
        return tb - ta;
      })
      .slice(0, 5);
  }, [projectInsight]);

  // ── Derived counts
  const queryRows = useMemo(() => queries ?? [], [queries]);
  const sourceRows = useMemo(
    () => (sources ?? []).filter((s) => !s.archived),
    [sources],
  );
  const dashboardRows = useMemo(() => dashboards ?? [], [dashboards]);
  const connectedSources = sourceRows.filter((s) => !isSaas(s)).length;
  const publishedDashboards = dashboardRows.filter(
    (d) => d.status.toLowerCase() === "published",
  ).length;
  const memberCount = (members ?? []).filter((m) => m.is_active).length;
  const aiActions = (activity?.events ?? []).filter((e) => e.category === "ai");
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

  const canEditProject = user.rawRole !== "viewer";

  const handleSourceCreated = () => {
    void queryClient.invalidateQueries({ queryKey: ["project", projectId, "datasources"] });
    void queryClient.invalidateQueries({ queryKey: ["project", projectId, "activity"] });
    push("Data source connected", "success");
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="overview"
      breadcrumbLabel="Overview"
      contextPanel={
        <ContextPanel
          title="AI Context"
          askPlaceholder="Ask about this project…"
          onAsk={handleAsk}
          collapsible
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

          <ContextSection title="Context health">
            <div className="flex items-center gap-2 text-[13px] text-ink-secondary">
              <span className="inline-block h-2 w-2 rounded-full bg-success" />
              Project isolation active
            </div>
            <p className="mt-1 text-small text-ink-tertiary">
              {sourceRows.length} source{sourceRows.length === 1 ? "" : "s"} connected ·{" "}
              {tableNodes.length} table{tableNodes.length === 1 ? "" : "s"} in scope
            </p>
          </ContextSection>

          <ContextSection title="In-scope assets">
            <ul className="space-y-1 text-[13px] text-ink-secondary">
              <li className="flex justify-between">
                <span>Data Sources</span>
                <span className="tabular-nums text-ink-primary">{sourceRows.length}</span>
              </li>
              <li className="flex justify-between">
                <span>Tables</span>
                <span className="tabular-nums text-ink-primary">{queryRows.length}</span>
              </li>
              <li className="flex justify-between">
                <span>Documents</span>
                <span className="tabular-nums text-ink-primary">
                  {project?.documentCount ?? 0}
                </span>
              </li>
              <li className="flex justify-between">
                <span>Dashboards</span>
                <span className="tabular-nums text-ink-primary">
                  {project?.dashboardCount ?? dashboardRows.length}
                </span>
              </li>
            </ul>
          </ContextSection>

          <ContextSection title="Recent AI Actions">
            {aiActions.length === 0 ? (
              <p className="text-small text-ink-tertiary">No AI actions yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {aiActions.slice(0, 4).map((e) => (
                  <li
                    key={e.id}
                    className="flex items-center justify-between gap-2 text-[13px]"
                  >
                    <span className="min-w-0 truncate text-ink-secondary">{e.title}</span>
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
      <div className="space-y-5">
        <ProjectHeader
          project={project}
          memberCount={memberCount}
          aiStatus={project?.aiStatus ?? "idle"}
          onMembers={() => setShowMembers(true)}
          onToast={push}
        />

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
            {chatError && <p className="text-small text-danger">{chatError}</p>}
          </div>
        )}

        <section aria-label="Project KPIs">
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
                queryRows.filter((q) => q.ai_generated).length > 0
                  ? `${queryRows.filter((q) => q.ai_generated).length} AI-generated`
                  : undefined
              }
            />
            <StatTile
              label="Documents"
              value={project?.documentCount ?? 0}
              hint={`${edges.length} relationship${edges.length === 1 ? "" : "s"}`}
            />
            <StatTile
              label="Dashboards"
              value={project?.dashboardCount ?? dashboardRows.length}
              hint={`${publishedDashboards} published`}
            />
            <StatTile
              label="AI Actions"
              value={activity?.stats?.ai_actions ?? aiActions.length}
              hint="All audited"
              hintTone="success"
            />
          </div>
        </section>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <RecentInsightsCard
            projectId={projectId}
            insights={recentInsights}
            generatedAt={projectInsight?.generatedAt}
          />
          <ProjectActivityCard events={activity?.events ?? []} />
          <QuickActionsCard
            projectId={projectId}
            canEdit={canEditProject}
            onSourceCreated={handleSourceCreated}
          />
        </div>
      </div>

      <MembersDialog
        open={showMembers}
        projectId={projectId}
        onClose={() => setShowMembers(false)}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}

function ProjectHeader({
  project,
  memberCount,
  aiStatus,
  onMembers,
  onToast,
}: {
  project: ProjectSummary | null;
  memberCount: number;
  aiStatus: AiStatus;
  onMembers: () => void;
  onToast: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const statusLabel = aiStatusLabel(aiStatus);
  const statusTone = aiStatusTone(aiStatus);
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-line-tertiary bg-bg-primary p-4">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-lg font-semibold text-white"
          style={{ backgroundColor: project?.accent ?? "var(--brand-500)" }}
        >
          {(project?.name ?? "P").slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-h1 text-ink-primary">{project?.name ?? "Project"}</h1>
            <Badge tone={statusTone} title={`Project status: ${statusLabel}`}>
              {statusLabel}
            </Badge>
          </div>
          <p className="mt-0.5 text-small text-ink-tertiary">
            {project?.visibility === "shared" ? "Shared" : "Private"} project
            {memberCount > 0 && ` · ${memberCount} member${memberCount === 1 ? "" : "s"}`}
            {project?.updatedLabel && ` · Updated ${project.updatedLabel}`}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ShareToggle
          projectId={String(project?.id ?? "")}
          shared={project?.visibility === "shared"}
          onToast={onToast}
        />
        <Button variant="secondary" onClick={onMembers}>
          <IconUsers size={14} />
          Members
        </Button>
      </div>
    </header>
  );
}

function RecentInsightsCard({
  projectId,
  insights,
  generatedAt,
}: {
  projectId: string;
  insights: Array<ProjectInsightCard & { category: string }>;
  generatedAt?: string;
}) {
  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="text-h3 text-ink-primary">Recent insights</span>
        <Link
          href={`/projects/${projectId}/insight`}
          className="text-[12px] font-medium text-brand-700 hover:underline"
        >
          View all
        </Link>
      </div>
      <div className="flex-1 p-2">
        {insights.length === 0 ? (
          <div className="px-2 py-8 text-center text-small text-ink-tertiary">
            No insights yet. Ask anything or generate insights to see findings here.
          </div>
        ) : (
          <ul className="space-y-1">
            {insights.map((insight) => (
              <li key={insight.id}>
                <a
                  href={`/projects/${projectId}/insight`}
                  className="group flex items-start gap-2 rounded-md px-2 py-2 hover:bg-bg-secondary"
                >
                  <Badge tone={severityTone(insight.severity)} size="sm">
                    {insightCategory(insight.category)}
                  </Badge>
                  <span className="min-w-0 flex-1 text-[13px] font-medium text-ink-primary group-hover:text-brand-700">
                    {insight.title}
                  </span>
                  <span className="shrink-0 text-small text-ink-tertiary">
                    {timeAgo(insight.executedAt ?? generatedAt ?? new Date().toISOString())}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

const ACTIVITY_META: Record<
  string,
  { icon: typeof IconSparkles; tone: "ai" | "brand" | "neutral" | "success" }
> = {
  ai: { icon: IconSparkles, tone: "ai" },
  query: { icon: IconCode, tone: "brand" },
  upload: { icon: IconDatabase, tone: "success" },
  dashboard: { icon: IconLayoutDashboard, tone: "neutral" },
  sync: { icon: IconDatabase, tone: "neutral" },
};

function ProjectActivityCard({ events }: { events: ActivityEvent[] }) {
  const rows = events.slice(0, 6);
  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="text-h3 text-ink-primary">Project activity</span>
      </div>
      <div className="flex-1 p-2">
        {rows.length === 0 ? (
          <div className="px-2 py-8 text-center text-small text-ink-tertiary">
            No recent activity.
          </div>
        ) : (
          <ul className="space-y-0.5">
            {rows.map((e) => {
              const meta = ACTIVITY_META[e.category] ?? ACTIVITY_META.sync;
              const Icon = meta.icon;
              return (
                <li
                  key={e.id}
                  className="flex items-start gap-2.5 rounded-md px-2 py-2 text-[13px]"
                >
                  <span
                    className={cn(
                      "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                      meta.tone === "ai" && "bg-ai-bg text-ai",
                      meta.tone === "brand" && "bg-brand-50 text-brand-700",
                      meta.tone === "success" && "bg-success-bg text-success",
                      meta.tone === "neutral" && "bg-bg-secondary text-ink-secondary",
                    )}
                  >
                    <Icon size={14} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-ink-primary">{e.title}</p>
                    <p className="text-small text-ink-tertiary">
                      {e.actor} · {timeAgo(e.ts)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

function QuickActionsCard({
  projectId,
  canEdit,
  onSourceCreated,
}: {
  projectId: string;
  canEdit: boolean;
  onSourceCreated: () => void;
}) {
  const router = useRouter();
  const actions = [
    {
      label: "Add data source",
      icon: IconDatabase,
      onClick: undefined as (() => void) | undefined,
      content: (
        <ConnectorsMenu
          projectId={Number(projectId)}
          onCreated={onSourceCreated}
          label="Add data source"
        />
      ),
    },
    {
      label: "Create table",
      icon: IconCode,
      onClick: () => router.push(`/projects/${projectId}/queries`),
    },
    {
      label: "Upload document",
      icon: IconFileText,
      onClick: () => router.push(`/projects/${projectId}/documents`),
    },
    {
      label: "New dashboard",
      icon: IconLayoutDashboard,
      onClick: () => router.push(`/projects/${projectId}/dashboards`),
    },
  ];

  return (
    <Card className="flex flex-col">
      <div className="border-b border-line-tertiary px-4 py-3">
        <span className="text-h3 text-ink-primary">Quick actions</span>
      </div>
      <div className="grid grid-cols-2 gap-2 p-3">
        {actions.map((action) => {
          const Icon = action.icon;
          const disabled = !canEdit;
          return (
            <div key={action.label}>
              {action.content ? (
                <div className="[&>div]:w-full [&_button]:w-full [&_button]:justify-center">
                  {action.content}
                </div>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={action.onClick}
                  title={disabled ? "You do not have permission to create project resources" : action.label}
                  className="w-full"
                >
                  <Icon size={14} />
                  {action.label}
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
