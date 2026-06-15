import { type ReactNode } from "react";
import type {
  CurrentUser,
  NavKey,
  ProjectSummary,
  TenantSummary,
} from "@/lib/ui/types";
import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

export interface AppShellProps {
  mode: "home" | "project";
  activeNav: NavKey;
  tenant: TenantSummary;
  user: CurrentUser;
  project?: ProjectSummary | null;
  otherProjects?: ProjectSummary[];
  counts?: Partial<Record<"projects" | "queries" | "documents", number>>;
  /** Top bar content (left/right). Falls back to a bare bar when omitted. */
  topBarLeft?: ReactNode;
  topBarRight?: ReactNode;
  /** Optional right-side context panel (project-context pages). */
  contextPanel?: ReactNode;
  /** When true, main content is centered with a max width (Home only). */
  centered?: boolean;
  children: ReactNode;
}

export function AppShell({
  mode,
  activeNav,
  tenant,
  user,
  project,
  otherProjects,
  counts,
  topBarLeft,
  topBarRight,
  contextPanel,
  centered = false,
  children,
}: AppShellProps) {
  return (
    <div className="flex h-screen bg-bg-secondary">
      <Sidebar
        mode={mode}
        activeNav={activeNav}
        tenant={tenant}
        user={user}
        project={project}
        otherProjects={otherProjects}
        counts={counts}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar left={topBarLeft} right={topBarRight} />
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto">
            <div
              className={
                centered
                  ? "mx-auto w-full max-w-content px-5 py-6"
                  : "px-5 py-5"
              }
            >
              {children}
            </div>
          </main>
          {contextPanel}
        </div>
      </div>
    </div>
  );
}
