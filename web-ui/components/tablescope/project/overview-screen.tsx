"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IconUsers, IconLoader2 } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { MembersDialog } from "@/components/tablescope/project/members-dialog";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { ContextPanel, ContextSection, IsolationCard } from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import {
  AiConversationsCard,
  recentConversationsKey,
} from "@/components/tablescope/project/ai-conversations-card";
import { QuickActionsCard } from "@/components/tablescope/project/quick-actions-card";
import {
  createConversation,
  getConversation,
  submitTurn,
  type Conversation,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import { projectInsightApi, type ProjectInsight, type ProjectInsightCard } from "@/lib/api/project-insight";
import { buildAiAssistantHref } from "@/lib/navigation/ai-assistant";
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
} from "@/lib/ui/use-project-data";import { isSaas } from "./overview-screen/is-saas";
import { PROJECT_INSIGHTS_TITLE } from "./overview-screen/project-insights-title";
import { PROJECT_INSIGHTS_SURFACE } from "./overview-screen/project-insights-surface";
import { pollConversation } from "./overview-screen/poll-conversation";
import { ProjectHeader } from "./overview-screen/project-header";
import { RecentInsightsCard } from "./overview-screen/recent-insights-card";



export function OverviewScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
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

  // A saved successful answer belongs in the permanent conversations panel
  // straight away; the on-page transcript stays as-is.
  const notePersistedTurns = useCallback(
    (turns: ConversationTurn[]) => {
      if (!turns.some((t) => t.status === "success")) return;
      void queryClient.invalidateQueries({ queryKey: recentConversationsKey(projectId) });
    },
    [projectId, queryClient],
  );

  const openInAssistant = useCallback(() => {
    if (chatConversationId == null) return;
    router.push(
      buildAiAssistantHref({
        conversationId: chatConversationId,
        projectId,
        origin: "project-overview",
      }),
    );
  }, [chatConversationId, projectId, router]);

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
          notePersistedTurns(polled.turns);
        } else {
          const res = await submitTurn(chatConversationId, { message });
          setChatTurns((prev) => [...prev, res.turn]);
          const polled = await pollConversation(res.conversation_id);
          setChatTurns(polled.turns);
          notePersistedTurns(polled.turns);
        }
      } catch (err) {
        setChatError(err instanceof Error ? err.message : "Ask failed");
      } finally {
        setChatBusy(false);
      }
    },
    [chatConversationId, notePersistedTurns, projectId],
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
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-h3 text-ink-primary">Ask Anything</h3>
              {chatConversationId && (
                <Button variant="ghost" size="sm" onClick={openInAssistant}>
                  Open in AI Assistant
                </Button>
              )}
            </div>
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[33fr_43fr_24fr]">
          <RecentInsightsCard
            projectId={projectId}
            insights={recentInsights}
            generatedAt={projectInsight?.generatedAt}
            hasData={
              sourceRows.length > 0 ||
              queryRows.length > 0 ||
              (project?.documentCount ?? 0) > 0
            }
          />
          <AiConversationsCard projectId={projectId} />
          <QuickActionsCard
            className="md:col-span-2 xl:col-span-1"
            projectId={projectId}
            canEdit={canEditProject}
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
