"use client";

import { useEffect, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconHelpCircle } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { IntelligenceFeed } from "@/components/tablescope/home/intelligence-feed";
import { getUserMeta } from "@/lib/auth";
import { greeting } from "@/lib/ui/format";
import {
  useCurrentUser,
  useProjectSummaries,
} from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";
import { createHomePin, getHomePins } from "@/lib/api/home-pins";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import {
  createConversation,
  getConversation,
  submitTurn,
  type Conversation,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import { IconLoader2 } from "@tabler/icons-react";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 50);
}

export default function BusinessInsightPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toasts, push: pushToast, dismiss } = useToasts();
  const { data: identity } = useCurrentUser();
  const { data: allProjects } = useProjectSummaries();

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const { data: homePins = [] } = useQuery({
    queryKey: ["home-pins"],
    queryFn: getHomePins,
  });

  const pinnedByFingerprint = useMemo(() => {
    const map = new Map<string, number>();
    for (const pin of homePins) {
      const payload = (pin.frozen_payload ?? pin.config ?? {}) as { evidenceFingerprint?: { resultFingerprint?: string }; insightId?: string };
      const key =
        payload.evidenceFingerprint?.resultFingerprint ??
        payload.insightId ??
        pin.pin_key;
      if (key) map.set(String(key), pin.id);
    }
    return map;
  }, [homePins]);

  const pinMutation = useMutation({
    mutationFn: createHomePin,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["home-pins"] });
      pushToast("Pinned to Home", "success");
    },
    onError: (err: Error) => pushToast(err.message, "error"),
  });

  const handlePinInsight = useCallback(
    (card: InsightCard) => {
      const key =
        card.evidenceFingerprint?.resultFingerprint ??
        card.insightId ??
        card.id;
      if (!key) {
        pushToast("Unable to pin this insight", "error");
        return;
      }
      if (pinnedByFingerprint.has(key)) {
        pushToast("This insight is already pinned to Home", "info");
        return;
      }
      pinMutation.mutate({
        pin_type: "insight_card",
        pin_key: `insight:${card.projectId}:${card.insightType}:${key}`,
        title: card.title,
        project_id: Number(card.projectId),
        frozen_payload: card as unknown as Record<string, unknown>,
        layout: { x: 0, y: 0, w: 6, h: 5 },
      });
    },
    [pinMutation, pinnedByFingerprint, pushToast],
  );

  const [chatTurns, setChatTurns] = useState<ConversationTurn[]>([]);
  const [chatConversationId, setChatConversationId] = useState<number | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [createActionOpen, setCreateActionOpen] = useState(false);
  const [selectedInsight, setSelectedInsight] = useState<ActionableInsight | null>(null);

  const handleCreateAction = useCallback((card: InsightCard) => {
    const insight: ActionableInsight = {
      insightId: card.insightId || card.id,
      insightType: card.insightType,
      title: card.title,
      summary: card.summary,
      severity: card.severity,
      projectId: card.projectId,
      projectName: card.projectName,
      recommendedAction: card.callout?.text || null,
      sources: card.sources,
      supportingSources: [
        ...(card.sources?.tables ?? []),
        ...(card.sources?.documents ?? []),
      ],
      explanation: card.explanation as Record<string, unknown> | undefined,
    };
    setSelectedInsight(insight);
    setCreateActionOpen(true);
  }, []);

  const pollConversation = useCallback(
    async (id: number): Promise<Conversation> => {
      for (let i = 0; i < 60; i++) {
        const data = await getConversation(id);
        const last = data.turns[data.turns.length - 1];
        if (!last || last.status !== "pending") return data;
        await new Promise((r) => setTimeout(r, 1000));
      }
      return getConversation(id);
    },
    [],
  );

  const handleAsk = useCallback(
    async (message: string) => {
      setChatBusy(true);
      setChatError(null);
      try {
        if (chatConversationId == null) {
          const created = await createConversation({
            title: "Business Insights",
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
    [chatConversationId, pollConversation],
  );

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="business-insight"
      tenant={tenant}
      user={user}
      scrollable={true}
      counts={{ projects: allProjects?.length }}
      topBarLeft={
        <span className="text-[15px] text-ink-secondary">
          {user.name ? greeting(user.name) : "Business Insight"}
        </span>
      }
      topBarRight={
        <>
          <StatusDot tone="online" className="mr-1" />
          <Button
            variant="secondary"
            size="md"
            onClick={() => router.push("/help")}
          >
            <IconHelpCircle size={15} />
            Help
          </Button>
        </>
      }
    >
      <div className="space-y-6 pb-24">
        <div className="mx-auto w-full max-w-content space-y-6">
          <HomeAiSuggestions onAsk={handleAsk} />
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
        </div>
        <IntelligenceFeed
          onPin={handlePinInsight}
          pinnedByFingerprint={pinnedByFingerprint}
          onCreateAction={handleCreateAction}
          availableProjects={allProjects ?? []}
        />
      </div>

      <CreateActionFromInsightDialog
        open={createActionOpen}
        onClose={() => setCreateActionOpen(false)}
        insight={selectedInsight}
      />

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </AppShell>
  );
}
