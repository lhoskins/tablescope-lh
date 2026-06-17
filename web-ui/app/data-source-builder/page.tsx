"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/tablescope/app-shell";
import { DataSourceBuilderWorkspace } from "@/components/tablescope/data-source-builder/workspace";
import { getUserMeta } from "@/lib/auth";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
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

export default function DataSourceBuilderPage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="data-source-builder"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      topBarLeft={
        <div className="flex items-baseline gap-3">
          <span className="text-h2 text-ink-primary">Data Source Builder</span>
          <span className="text-small text-ink-tertiary">
            Manage sources across projects in one session
          </span>
        </div>
      }
    >
      <DataSourceBuilderWorkspace tenantName={tenant.name} />
    </AppShell>
  );
}
