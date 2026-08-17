"use client";


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IconLoader2 } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { MembersDialog } from "@/components/tablescope/project/members-dialog";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import { ProjectResourceTabs } from "@/components/tablescope/project/project-resource-tabs";
import { recentConversationsKey } from "@/components/tablescope/project/ai-conversations-card";
import {
  createConversation,
  getConversation,
  submitTurn,
  type Conversation,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import { projectInsightApi, type ProjectInsight, type ProjectInsightCard } from "@/lib/api/project-insight";
import { buildAiAssistantHref } from "@/lib/navigation/ai-assistant";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectShell,
  useProjectQueries,
  useProjectDataSources,
  useProjectDashboards,
  useProjectMembers,
  useProjectActivity,
  useProjectGraph,
} from "@/lib/ui/use-project-data";
import { PROJECT_INSIGHTS_TITLE } from "./overview-screen/project-insights-title";
import { PROJECT_INSIGHTS_SURFACE } from "./overview-screen/project-insights-surface";
import { pollConversation } from "./overview-screen/poll-conversation";
import { ProjectHeader } from "./overview-screen/project-header";
import { RecentActivityFeed } from "./overview-screen/recent-activity-feed";
import { StatBar } from "./overview-screen/stat-bar";



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
  const [askValue, setAskValue] = useState("");

  // The composer is pinned; new turns render at the bottom of the scrollable
  // area right above it, so keep that area scrolled to the newest turn —
  // the same behavior a chat interface gives for free.
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (chatTurns.length === 0 && !chatBusy) return;
    scrollAreaRef.current?.scrollTo({
      top: scrollAreaRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [chatTurns, chatBusy]);

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

  const submitAsk = useCallback(
    (message: string) => {
      setAskValue("");
      void handleAsk(message);
    },
    [handleAsk],
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

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="overview"
      breadcrumbLabel="Overview"
      scrollable={false}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <ProjectHeader
          project={project}
          memberCount={memberCount}
          aiStatus={project?.aiStatus ?? "idle"}
          onMembers={() => setShowMembers(true)}
          onToast={push}
        />

        <div className="-mx-5">
          <ProjectResourceTabs projectId={projectId} />
        </div>

        {/* Scrollable content — the composer below never moves with it. */}
        <div ref={scrollAreaRef} className="min-h-0 flex-1 space-y-5 overflow-y-auto pb-4">
          <StatBar
            projectId={projectId}
            dataSources={sourceRows.length}
            tables={project?.queryCount ?? queryRows.length}
            documents={project?.documentCount ?? 0}
            dashboards={project?.dashboardCount ?? dashboardRows.length}
            aiActions={activity?.stats?.ai_actions ?? aiActions.length}
          />

          <RecentActivityFeed
            projectId={projectId}
            insights={recentInsights}
            generatedAt={projectInsight?.generatedAt}
            hasData={
              sourceRows.length > 0 ||
              queryRows.length > 0 ||
              (project?.documentCount ?? 0) > 0
            }
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
        </div>

        {/* Pinned composer — stays in view like a chat input, never scrolls
            away with the content above it. chatTurns/chatBusy/chatError are
            plain React state (never persisted), so a refresh clears any
            result the same way it always has. */}
        <div className="shrink-0 border-t border-line-tertiary pt-4">
          <AskAnythingComposer
            value={askValue}
            onChange={setAskValue}
            onSubmit={submitAsk}
            placeholder="Ask anything across your connected data, documents, and dashboards"
            ariaLabel="Ask anything across your connected data, documents, and dashboards"
            busy={chatBusy}
            projectId={Number(projectId)}
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
