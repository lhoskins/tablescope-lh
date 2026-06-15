"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { IconHelpCircle } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { HeroSearch } from "@/components/tablescope/home/hero-search";
import {
  QuickActionGrid,
  type QuickActionKey,
} from "@/components/tablescope/home/quick-actions";
import { RecentProjectsTable } from "@/components/tablescope/home/recent-projects";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
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
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  const handleQuickAction = (key: QuickActionKey) => {
    if (key === "new-project") {
      setShowCreate(true);
    }
  };

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
        </>
      }
    >
      <div className="space-y-10 py-6">
        <HeroSearch />
        <QuickActionGrid onAction={handleQuickAction} />
        <RecentProjectsTable
          projects={isLoading ? [] : (projects ?? [])}
        />
      </div>
      <NewProjectDialog open={showCreate} onClose={() => setShowCreate(false)} />
    </AppShell>
  );
}
