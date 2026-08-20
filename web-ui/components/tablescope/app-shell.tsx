import { type ReactNode } from "react";
import type {
  CurrentUser,
  NavKey,
  ProjectSummary,
  TenantSummary,
} from "@/lib/ui/types";
import { MfaGate } from "@/components/auth/mfa-gate";
import { CompanyLogo } from "./company-logo";
import { MobileNav } from "./mobile-nav";
import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

export interface AppShellProps {
  mode: "home" | "project";
  activeNav: NavKey;
  tenant: TenantSummary;
  user: CurrentUser;
  project?: ProjectSummary | null;
  otherProjects?: ProjectSummary[];
  counts?: Partial<Record<"projects" | "queries" | "documents" | "actionCount", number>>;
  /** Top bar content (left/right). Falls back to a bare bar when omitted. */
  topBarLeft?: ReactNode;
  topBarRight?: ReactNode;
  /** Optional sub-header rendered below the top bar (e.g. project resource tabs). */
  subHeader?: ReactNode;
  /** Optional right-side context panel (project-context pages). */
  contextPanel?: ReactNode;
  /** When true, main content is centered with a max width (Home only). */
  centered?: boolean;
  /** When false, the main content area does not scroll (use for full-screen pages). */
  scrollable?: boolean;
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
  subHeader,
  contextPanel,
  centered = false,
  scrollable = true,
  children,
}: AppShellProps) {
  return (
    <div className="flex h-dvh overflow-hidden bg-bg-secondary">
      <MfaGate />
      <div className="hidden lg:flex">
        <Sidebar
          mode={mode}
          activeNav={activeNav}
          tenant={tenant}
          user={user}
          project={project}
          otherProjects={otherProjects}
          counts={counts}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* The company logo stays alone in the header — page/workspace action
            buttons render in the page toolbar below (see topBarRight), so they
            no longer share space with the branding. */}
        <TopBar
          left={
            <>
              <MobileNav
                mode={mode}
                activeNav={activeNav}
                tenant={tenant}
                user={user}
                project={project}
                otherProjects={otherProjects}
                counts={counts}
              />
              {topBarLeft}
            </>
          }
          right={<CompanyLogo url={tenant.logoUrl} name={tenant.name} />}
        />
        {subHeader && (
          <div className="shrink-0 border-b border-line-tertiary bg-bg-primary">
            {subHeader}
          </div>
        )}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <main
            className={`relative min-h-0 flex-1 ${scrollable ? "overflow-y-auto" : "overflow-hidden"}`}
          >
            <div
              className={
                centered
                  ? "mx-auto w-full min-w-0 max-w-content px-5 py-6"
                  : scrollable
                    ? "min-w-0 px-5 py-5"
                    : "flex h-full min-h-0 min-w-0 flex-col px-5 py-5"
              }
            >
              {topBarRight && (
                <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
                  {topBarRight}
                </div>
              )}
              {children}
            </div>
          </main>
          {contextPanel}
        </div>
      </div>
    </div>
  );
}
