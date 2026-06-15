"use client";

import { type ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "./app-shell";
import { Breadcrumb } from "./top-bar";
import { getUserMeta } from "@/lib/auth";
import { useProjectShell } from "@/lib/ui/use-project-data";
import type { NavKey } from "@/lib/ui/types";

export function ProjectShell({
  projectId,
  activeNav,
  breadcrumbLabel,
  actions,
  contextPanel,
  children,
}: {
  projectId: string;
  activeNav: NavKey;
  breadcrumbLabel: string;
  actions?: ReactNode;
  contextPanel?: ReactNode;
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
      topBarLeft={
        <Breadcrumb
          items={[
            { label: project?.name ?? "Project", href: `/projects/${projectId}` },
            { label: breadcrumbLabel },
          ]}
        />
      }
      topBarRight={actions}
      contextPanel={contextPanel}
    >
      {children}
    </AppShell>
  );
}
