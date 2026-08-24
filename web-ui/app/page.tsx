"use client";

import { useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { IconHelpCircle, IconAdjustmentsHorizontal } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { HomePinsGrid } from "@/components/tablescope/home/home-pins-grid";
import { PersonalizedHome } from "@/components/tablescope/home/personalized-home";
import { WorkspaceAssistantPanel } from "@/components/tablescope/project/workspace/workspace-assistant-panel";
import { getUserMeta } from "@/lib/auth";
import { greeting } from "@/lib/ui/format";
import {
  useCurrentUser,
  useProjectSummaries,
} from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

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

export default function HomePage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: allProjects } = useProjectSummaries();
  const personalizeRef = useRef<() => void>(() => undefined);
  const registerPersonalize = useCallback((handler: () => void) => {
    personalizeRef.current = handler;
  }, []);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="home"
      tenant={tenant}
      user={user}
      counts={{ projects: allProjects?.length }}
      contextPanel={
        <WorkspaceAssistantPanel
          surface="business_insights"
          contextLabel="Personal Home"
        />
      }
      topBarRight={
        <>
          <Button variant="secondary" size="md" onClick={() => personalizeRef.current()}>
            <IconAdjustmentsHorizontal size={15} />
            Personalize Home
          </Button>
          <StatusDot tone="online" className="ml-1 mr-1" />
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
      <div className="space-y-6 pb-8">
        <div>
          <h1 className="text-h1 text-ink-primary">
            {user.name ? greeting(user.name) : "Home"}
          </h1>
          <p className="mt-1 text-body text-ink-tertiary">
            Your priorities, assigned work, and the insights you chose to follow.
          </p>
        </div>
        <PersonalizedHome
          projectCount={allProjects?.length ?? 0}
          onPersonalize={registerPersonalize}
        />
        <HomePinsGrid />
      </div>
    </AppShell>
  );
}
