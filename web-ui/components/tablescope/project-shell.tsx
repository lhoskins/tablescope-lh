"use client";

import { type ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "./app-shell";
import { ProjectResourceTabs } from "./project/project-resource-tabs";
import { ProjectHeader } from "./project/overview-screen/project-header";
import { MembersDialog } from "./project/members-dialog";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { getUserMeta } from "@/lib/auth";
import { useProjectShell, useProjectMembers } from "@/lib/ui/use-project-data";
import type { NavKey, ProjectSummary } from "@/lib/ui/types";

export function ProjectShell({
  projectId,
  activeNav,
  actions,
  contextPanel,
  scrollable,
  showResourceTabs = true,
  showProjectHeader = false,
  headerActions,
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
  /** Render the resource tab menu in the sub-header. Pages that render their
   *  own title/header can set this to false and place the tabs below the title. */
  showResourceTabs?: boolean;
  /** Render a project title header and resource tabs above the page content.
   *  Use this on project inventory pages (Data Sources, Tables, Documents)
   *  to match the Project Overview layout. */
  showProjectHeader?: boolean;
  /** Actions placed in the right side of the project title header. */
  headerActions?: ReactNode;
  children: ReactNode;
}) {
  const router = useRouter();
  const { user, tenant, project, otherProjects, counts } =
    useProjectShell(projectId);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const renderHeader = showProjectHeader && activeNav !== "overview";

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
        activeNav === "overview" || !showResourceTabs || renderHeader
          ? undefined
          : (
              <ProjectResourceTabs projectId={projectId} />
            )
      }
      contextPanel={contextPanel}
      scrollable={scrollable}
    >
      {renderHeader ? (
        <ProjectPageHeader
          projectId={projectId}
          project={project}
          headerActions={headerActions}
        >
          {children}
        </ProjectPageHeader>
      ) : (
        children
      )}
    </AppShell>
  );
}

function ProjectPageHeader({
  projectId,
  project,
  headerActions,
  children,
}: {
  projectId: string;
  project: ProjectSummary | null;
  headerActions?: ReactNode;
  children: ReactNode;
}) {
  const { data: members } = useProjectMembers(projectId);
  const memberCount = (members ?? []).filter((m) => m.is_active).length;
  const [showMembers, setShowMembers] = useState(false);
  const { toasts, push, dismiss } = useToasts();

  return (
    <div className="flex flex-col gap-4">
      <ProjectHeader
        project={project}
        memberCount={memberCount}
        aiStatus={project?.aiStatus ?? "idle"}
        onMembers={() => setShowMembers(true)}
        onToast={push}
        actions={headerActions}
      />
      <div className="-mx-5">
        <ProjectResourceTabs projectId={projectId} />
      </div>
      {children}
      <MembersDialog
        open={showMembers}
        projectId={projectId}
        onClose={() => setShowMembers(false)}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
