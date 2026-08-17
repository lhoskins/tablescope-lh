"use client";

import { type ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";
import { AppShell } from "./app-shell";
import { Breadcrumb } from "./top-bar";
import { ProjectResourceTabs } from "./project/project-resource-tabs";
import { getUserMeta } from "@/lib/auth";
import { useProjectShell } from "@/lib/ui/use-project-data";
import type { NavKey } from "@/lib/ui/types";

export function ProjectShell({
  projectId,
  activeNav,
  breadcrumbLabel,
  actions,
  contextPanel,
  scrollable,
  children,
}: {
  projectId: string;
  activeNav: NavKey;
  breadcrumbLabel: string;
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
      topBarLeft={
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            aria-label="Back to projects"
            title="Back to projects"
            onClick={() => router.push("/projects")}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-tertiary hover:bg-brand-50/60 hover:text-ink-primary"
          >
            <IconArrowLeft size={16} />
          </button>
          <Breadcrumb
            items={[
              { label: project?.name ?? "Project", href: `/projects/${projectId}` },
              { label: breadcrumbLabel },
            ]}
          />
        </div>
      }
      topBarRight={actions}
      subHeader={<ProjectResourceTabs projectId={projectId} />}
      contextPanel={contextPanel}
      scrollable={scrollable}
    >
      {children}
    </AppShell>
  );
}
