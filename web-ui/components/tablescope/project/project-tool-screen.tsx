"use client";

import { type ReactNode } from "react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Breadcrumb } from "@/components/tablescope/top-bar";
import { getUserMeta } from "@/lib/auth";
import { useProjectShell } from "@/lib/ui/use-project-data";
import type { NavKey } from "@/lib/ui/types";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

interface ProjectToolScreenProps {
  projectId: string;
  activeNav: NavKey;
  breadcrumbLabel: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function ProjectToolScreen({
  projectId,
  activeNav,
  breadcrumbLabel,
  actions,
  children,
}: ProjectToolScreenProps) {
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
            {
              label: project?.name ?? "Project",
              href: `/projects/${projectId}`,
            },
            { label: breadcrumbLabel },
          ]}
        />
      }
      topBarRight={actions}
    >
      {children}
    </AppShell>
  );
}
