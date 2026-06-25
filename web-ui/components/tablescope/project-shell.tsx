"use client";

import { type ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { IconArrowLeft } from "@tabler/icons-react";
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
        <div className="flex items-center gap-2">
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
      contextPanel={contextPanel}
    >
      {children}
    </AppShell>
  );
}
