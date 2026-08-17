"use client";

import { type ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "./app-shell";
import { ProjectResourceTabs } from "./project/project-resource-tabs";
import { getUserMeta } from "@/lib/auth";
import { useProjectShell } from "@/lib/ui/use-project-data";
import type { NavKey } from "@/lib/ui/types";

export function ProjectShell({
  projectId,
  activeNav,
  actions,
  contextPanel,
  scrollable,
  children,
}: {
  projectId: string;
  activeNav: NavKey;
  breadcrumbLabel?: string;
  actions?: ReactNode;
  contextPanel?: ReactNode;
  /** When false, the main content area does not scroll — the page manages
   *  its own internal scroll region (e.g. a pinned bottom composer). */
  scrollable?: boolean;
  children: ReactNode;
}) {
  const router = useRouter();
  const { user, tenant, project, otherProjects, counts } =
    useProjectShell(projectId);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  return (
    <AppShell
      mode="project"
      activeNav={activeNav}
      tenant={tenant}
      user={user}
      project={project}
      otherProjects={otherProjects}
      counts={counts}
      topBarRight={actions}
      subHeader={
        activeNav === "overview" ? undefined : (
          <ProjectResourceTabs projectId={projectId} />
        )
      }
      contextPanel={contextPanel}
      scrollable={scrollable}
    >
      {children}
    </AppShell>
  );
}
