"use client";

import { useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import { createHomePin } from "@/lib/api/home-pins";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { useToasts, ToastViewport } from "@/components/ui/toast";

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
      pinMutation.mutate({
        pin_type: "insight_card",
        pin_key: `insight:${card.projectId}:${card.insightType}:${slugify(card.title)}`,
        title: card.title,
        project_id: Number(card.projectId),
        frozen_payload: card as unknown as Record<string, unknown>,
        layout: { x: 0, y: 0, w: 6, h: 5 },
      });
    },
    [pinMutation],
  );

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="business-insight"
      tenant={tenant}
      user={user}
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
      <div className="space-y-10 py-6">
        <div className="mx-auto w-full max-w-content space-y-6">
          <HomeAiSuggestions />
        </div>
        <IntelligenceFeed onPin={handlePinInsight} />
      </div>

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </AppShell>
  );
}
