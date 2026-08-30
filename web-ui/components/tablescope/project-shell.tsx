"use client";

import { type ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "./app-shell";
import { ProjectNavGrid } from "./project/project-nav-grid";
import {
  ProjectTitleBreadcrumb,
  ProjectTopBarControls,
} from "./project/project-topbar";
import { MembersDialog } from "./project/members-dialog";
import { WorkspaceTabsBar } from "./project/workspace/workspace-tabs-bar";
import { WorkspaceAssistantPanel } from "./project/workspace/workspace-assistant-panel";
import { projectGridItems } from "./nav";
import type { WorkspaceTab } from "./project/workspace/workspace-tabs-storage";
import type { WorkspaceCard } from "@/lib/api/workspaces";
import { ToastViewport, useToasts } from "@/components/ui/toast";
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
  showResourceTabs = true,
  workspaceItem = null,
  assistantSurface = "project_workspace",
  assistantContextLabel,
  assistantDefaultOpen = false,
  assistantWorkspaceCards = null,
  children,
}: {
  projectId: string;
  activeNav: NavKey;
  /** Screen segment of the top bar title (`API Costs › Documents`). Falls
   *  back to the matching nav card's label. */
  breadcrumbLabel?: string;
  /** Page-specific buttons. They sit in the top bar, left of the project's
   *  Private/Shared switch and Members button. */
  actions?: ReactNode;
  contextPanel?: ReactNode;
  /** When false, the main content area does not scroll — the page manages
   *  its own internal scroll region (e.g. a pinned bottom composer). */
  scrollable?: boolean;
  /** Render the "recently opened items" MRU strip (`WorkspaceTabsBar`) below
   *  the project nav grid. The nav grid itself always renders regardless of
   *  this flag -- it's the project's persistent top-level navigation, not a
   *  per-page resource strip. */
  showResourceTabs?: boolean;
  /** The specific table/dashboard/document/data source this page currently
   *  has open, if any. Feeds the project workspace tab strip and grounds the
   *  docked AI Assistant. */
  workspaceItem?: WorkspaceTab | null;
  /** Canonical AI Assistant conversation surface for this project page. */
  assistantSurface?: "project_insights" | "project_workspace";
  /** Stable label shown when the assistant is grounded on the page itself. */
  assistantContextLabel?: string;
  /** Open the docked AI Assistant by default (Workspace page only) unless the
   *  user has already expressed a preference. */
  assistantDefaultOpen?: boolean;
  /** Cards of the active named workspace, grounding the assistant on all of
   *  them instead of the single `workspaceItem`. */
  assistantWorkspaceCards?: WorkspaceCard[] | null;
  children: ReactNode;
}) {
  const router = useRouter();
  const { user, tenant, project, otherProjects, counts } =
    useProjectShell(projectId);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const [showMembers, setShowMembers] = useState(false);
  const { toasts, push, dismiss } = useToasts();

  const screenLabel =
    breadcrumbLabel ??
    projectGridItems(projectId).find((item) => item.key === activeNav)?.label;

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
        <ProjectTitleBreadcrumb
          project={project}
          screenLabel={screenLabel}
          aiStatus={project?.aiStatus ?? "idle"}
          onToast={push}
        />
      }
      topBarControls={
        <ProjectTopBarControls
          project={project}
          actions={actions}
          onMembers={() => setShowMembers(true)}
          onToast={push}
        />
      }
      subHeader={
        <>
          <ProjectNavGrid projectId={projectId} activeNav={activeNav} />
          {showResourceTabs && (
            <WorkspaceTabsBar projectId={projectId} activeItem={workspaceItem} />
          )}
        </>
      }
      contextPanel={
        <>
          {contextPanel}
          <WorkspaceAssistantPanel
            projectId={projectId}
            activeItem={workspaceItem}
            surface={assistantSurface}
            contextLabel={assistantContextLabel}
            workspaceCards={assistantWorkspaceCards}
            defaultOpen={assistantDefaultOpen}
          />
        </>
      }
      scrollable={scrollable}
    >
      {children}
      <MembersDialog
        open={showMembers}
        projectId={projectId}
        onClose={() => setShowMembers(false)}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </AppShell>
  );
}
