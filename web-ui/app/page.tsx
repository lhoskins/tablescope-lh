"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { IconHelpCircle } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { getUserMeta } from "@/lib/auth";
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
      <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
        <h1 className="text-h1 text-ink-primary">Home</h1>
        <p className="mt-2 max-w-md text-body text-ink-tertiary">
          This page is reserved for future development. Visit{" "}
          <button
            type="button"
            className="text-brand-700 underline hover:text-brand-800"
            onClick={() => router.push("/business-insight")}
          >
            Business Insight
          </button>{" "}
          for AI suggestions and intelligence.
        </p>
      </div>
    </AppShell>
  );
}
