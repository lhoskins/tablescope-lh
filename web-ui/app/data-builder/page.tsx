"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AppShell } from "@/components/tablescope/app-shell";
import {
  HomeDataBuilder,
  type HomeBuilderTab,
} from "@/components/tablescope/data-source-builder/home-data-builder";
import type { SourceTab } from "@/components/tablescope/data-source-builder/source-method-tabs";
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

function toTab(value: string | null): HomeBuilderTab {
  return value === "connected" || value === "all" ? value : "builder";
}

function toMethod(value: string | null): SourceTab | undefined {
  return value === "upload" ||
    value === "url" ||
    value === "database" ||
    value === "network"
    ? value
    : undefined;
}

function DataBuilderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: identity } = useCurrentUser();
  const { data: allProjects } = useProjectSummaries();

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;
  const tab = toTab(searchParams.get("tab"));
  const method = toMethod(searchParams.get("method"));

  return (
    <AppShell
      mode="home"
      activeNav="data-sources"
      tenant={tenant}
      user={user}
      counts={{ projects: allProjects?.length }}
      topBarLeft={
        <span className="text-h2 text-ink-primary">Data Builder</span>
      }
    >
      {/* Not `tenant.name`: that falls back to "Tablescope" until identity
          loads, and the builder store's ensureTenant wipes the whole staged
          session whenever the key changes -- so a file staged before identity
          arrived vanished the moment the real tenant name did. The empty
          string is the in-project page's convention; ensureTenant early-returns
          on it. */}
      <HomeDataBuilder
        tenantName={identity?.tenant.name ?? ""}
        tab={tab}
        method={method}
        onTabChange={(next) =>
          router.push(
            next === "builder" ? "/data-builder" : `/data-builder?tab=${next}`,
          )
        }
      />
    </AppShell>
  );
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <DataBuilderPage />
    </Suspense>
  );
}
