"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { IconHelpCircle, IconPlus } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { HeroSearch } from "@/components/tablescope/home/hero-search";
import { QuickActionGrid } from "@/components/tablescope/home/quick-actions";
import { RecentProjectsTable } from "@/components/tablescope/home/recent-projects";
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
  const { data: projects, isLoading } = useProjectSummaries({
    recent: true,
    limit: 5,
  });
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
      centered
      topBarLeft={
        <span className="text-[15px] text-ink-secondary">
          {user.name ? greeting(user.name) : "Welcome"}
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
          <Button
            variant="primary"
            size="md"
            onClick={() => router.push("/projects/new")}
          >
            <IconPlus size={15} />
            New project
          </Button>
        </>
      }
    >
      <div className="space-y-10 py-6">
        <HeroSearch />
        <QuickActionGrid />
        <RecentProjectsTable
          projects={isLoading ? [] : (projects ?? [])}
        />
      </div>
    </AppShell>
  );
}
