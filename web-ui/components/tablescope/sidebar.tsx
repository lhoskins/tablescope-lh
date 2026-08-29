"use client";


import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import {
  IconChevronDown,
  IconUsers,
  IconUserCircle,
  IconLogout,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconSettings,
} from "@tabler/icons-react";
import { signOut } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { accentFor } from "@/lib/ui/color";
import type {
  CurrentUser,
  NavKey,
  ProjectSummary,
  TenantSummary,
} from "@/lib/ui/types";

import {
  homeNavGroups,
  canViewSettings,
  type NavItem,
} from "./nav";import { COLLAPSE_STORAGE_KEY } from "./sidebar/collapse-storage-key";
import { SidebarProps } from "./sidebar/sidebar-props";
import { NavGroupBlock } from "./sidebar/nav-group-block";
import { NavRow } from "./sidebar/nav-row";
import { AccountMenu } from "./sidebar/account-menu";
import { ProjectsTree } from "./sidebar/projects-tree";



export function Sidebar({
  mode,
  activeNav,
  tenant,
  user,
  project,
  counts,
  className,
}: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(
        window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "true",
      );
    } catch {
      /* ignore */
    }
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((v) => {
      const next = !v;
      try {
        window.localStorage.setItem(COLLAPSE_STORAGE_KEY, String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  // The sidebar's core nav (Home / Business Insight / Projects / AI Assistant)
  // stays identical between home and project mode -- it no longer switches
  // its link set per page (see docs/ux-workspace-redesign-gap-analysis.md
  // §2). "Projects" is spliced out of that list and rendered as the
  // disclosure tree instead of a plain link.
  const homeItems = homeNavGroups(user)[0].items;
  const projectsIndex = homeItems.findIndex((i) => i.key === "projects");
  const beforeProjects = homeItems.slice(0, projectsIndex);
  const afterProjects = homeItems.slice(projectsIndex + 1);

  const isPlatformAdmin =
    Boolean(user.isSuperAdmin) || user.rawRole === "root_admin";

  const adminManagementItems: NavItem[] = canViewSettings(user)
    ? [
        {
          key: "admin-settings",
          label: "Settings",
          href: "/admin/settings",
          icon: IconSettings,
        },
      ]
    : [];

  if (isPlatformAdmin) {
    adminManagementItems.push({
      key: "admin-users",
      label: "Users",
      href: "/admin/users",
      icon: IconUsers,
    });
  }

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r border-line-tertiary bg-bg-primary transition-[width] duration-200",
        collapsed ? "w-14" : "w-sidebar",
        className,
      )}
    >
      {collapsed ? (
        <div className="flex flex-col items-center gap-1 px-2 py-3">
          <Link
            href="/"
            title="Tablescope home"
            aria-label="Tablescope home"
            className="transition-opacity hover:opacity-80"
          >
            <span className="text-h2 font-bold text-ink-primary">T</span>
          </Link>
          <button
            type="button"
            onClick={toggleCollapsed}
            title="Expand sidebar"
            aria-label="Expand sidebar"
            className="flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconLayoutSidebarLeftExpand size={18} />
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 px-4 py-3.5">
          <Link
            href="/"
            aria-label="Tablescope home"
            className="flex min-w-0 flex-1 items-center gap-2 transition-opacity hover:opacity-80"
          >
            <span className="truncate text-h2 font-bold text-ink-primary">Tablescope</span>
          </Link>
          <button
            type="button"
            onClick={toggleCollapsed}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconLayoutSidebarLeftCollapse size={18} />
          </button>
        </div>
      )}

      {/* Selector pill */}
      <div className={cn("pb-2", collapsed ? "px-2" : "px-3")}>
        {mode === "project" && project ? (
          <Link
            href={`/projects/${project.id}`}
            title={collapsed ? project.name : undefined}
            className={cn(
              "flex items-center rounded-md border border-line-secondary text-[13px] font-medium text-ink-primary hover:bg-bg-secondary",
              collapsed ? "justify-center px-0 py-2" : "gap-2 px-2.5 py-2",
            )}
          >
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: project.accent ?? accentFor(project.id) }}
            />
            {!collapsed && (
              <>
                <span className="flex-1 truncate">{project.name}</span>
                <IconChevronDown size={14} className="text-ink-tertiary" />
              </>
            )}
          </Link>
        ) : (
          <div
            className={cn(
              "flex items-center rounded-md border border-line-secondary",
              collapsed ? "justify-center px-0 py-2" : "gap-2 px-2.5 py-2",
            )}
            title={collapsed ? tenant.name : undefined}
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand-50 text-[10px] font-semibold text-brand-700">
              {tenant.initials}
            </span>
            {!collapsed && (
              <span className="flex-1 truncate text-[13px] font-medium text-ink-primary">
                {tenant.name}
              </span>
            )}
          </div>
        )}
      </div>

      <nav
        className={cn(
          "flex-1 space-y-1 overflow-y-auto pb-4",
          collapsed ? "px-2" : "px-3",
        )}
      >
        <div className="space-y-0.5">
          {beforeProjects.map((item) => (
            <NavRow
              key={item.key}
              item={item}
              active={item.key === activeNav}
              count={item.countKey ? counts?.[item.countKey] : undefined}
              collapsed={collapsed}
            />
          ))}
          <ProjectsTree
            currentProjectId={mode === "project" ? project?.id : null}
            collapsed={collapsed}
          />
          {afterProjects.map((item) => (
            <NavRow
              key={item.key}
              item={item}
              active={item.key === activeNav}
              count={item.countKey ? counts?.[item.countKey] : undefined}
              collapsed={collapsed}
            />
          ))}
        </div>

        {mode === "home" && adminManagementItems.length > 0 && (
          <NavGroupBlock
            group={{ heading: "Administration", items: adminManagementItems }}
            activeNav={activeNav}
            collapsed={collapsed}
          />
        )}
      </nav>

      <AccountMenu user={user} collapsed={collapsed} />
    </aside>
  );
}
