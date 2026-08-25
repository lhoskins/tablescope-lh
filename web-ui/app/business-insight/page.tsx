"use client";

import { useEffect, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconHelpCircle, IconSparkles } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { IntelligenceFeed } from "@/components/tablescope/home/intelligence-feed";
import { WorkspaceAssistantPanel } from "@/components/tablescope/project/workspace/workspace-assistant-panel";
import { getUserMeta } from "@/lib/auth";
import {
  useCurrentUser,
  useProjectSummaries,
} from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";
import { createHomePin, getHomePins } from "@/lib/api/home-pins";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { useToasts, ToastViewport } from "@/components/ui/toast";
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
        destination: "home",
        title: card.title,
        project_id: Number(card.projectId),
        frozen_payload: card as unknown as Record<string, unknown>,
        layout: { x: 0, y: 0, w: 6, h: 5 },
      });
    },
    [pinMutation, pinnedByFingerprint, pushToast],
  );

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
      contextPanel={
        <WorkspaceAssistantPanel
          surface="business_insights"
          contextLabel="Business Insights"
        />
      }
    >
      <div className="space-y-6 pb-24">
        <div className="mx-auto w-full max-w-content">
          <IntelligenceFeed
            onPin={handlePinInsight}
            pinnedByFingerprint={pinnedByFingerprint}
            onCreateAction={handleCreateAction}
            availableProjects={allProjects ?? []}
            actionsDisclosure="collapsible"
            presentation="executive"
            header={
              <div>
                <div className="mb-1.5 flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
                  <IconSparkles size={14} className="text-brand-500" />
                  Executive perspective · AI briefing
                </div>
                <h1 className="text-h1 text-ink-primary">Business Insights</h1>
                <p className="mt-1 text-body text-ink-tertiary">
                  Material changes across the projects and data you are authorized to view.
                </p>
              </div>
            }
          />
        </div>
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
