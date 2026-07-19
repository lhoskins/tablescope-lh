"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { IconHelpCircle } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { HomePinsGrid } from "@/components/tablescope/home/home-pins-grid";
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
      <div className="space-y-6 py-6">
        <div>
          <h1 className="text-h1 text-ink-primary">
            {user.name ? greeting(user.name) : "Home"}
          </h1>
          <p className="mt-1 text-body text-ink-tertiary">
            Pin insights and dashboards from Business Insight to build your
            personal overview.
          </p>
        </div>
        <HomeAiSuggestions />
        <HomePinsGrid />
      </div>
    </AppShell>
  );
}
