"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import {
  IconChevronDown,
  IconPlus,
  IconUsers,
  IconBuildingBank,
  IconShieldLock,
  IconDatabaseShare,
  IconPhoto,
  IconMathFunction,
  IconBrain,
  IconUserCircle,
  IconLogout,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
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
import { BrandMark } from "./brand-mark";
import {
  homeNavGroups,
  projectNavGroups,
  type NavGroup,
  type NavItem,
} from "./nav";

const COLLAPSE_STORAGE_KEY = "tablescope:sidebar-collapsed";

export interface SidebarProps {
  mode: "home" | "project";
  activeNav: NavKey;
  tenant: TenantSummary;
  user: CurrentUser;
  project?: ProjectSummary | null;
  otherProjects?: ProjectSummary[];
  counts?: Partial<Record<"projects" | "queries" | "documents", number>>;
}

function NavRow({
  item,
  active,
  count,
  collapsed,
}: {
  item: NavItem;
  active: boolean;
  count?: number;
  collapsed: boolean;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      title={collapsed ? item.label : undefined}
      aria-label={collapsed ? item.label : undefined}
      className={cn(
        "relative flex items-center rounded-md text-[13px]",
        collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-2.5 py-1.5",
        active
          ? "bg-brand-50 font-semibold text-brand-500"
          : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
      )}
    >
      <Icon size={collapsed ? 18 : 15} stroke={1.8} className="shrink-0" />
      {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
      {!collapsed && typeof count === "number" && count > 0 && (
        <span className="rounded-full bg-brand-50 px-1.5 text-[11px] font-medium text-brand-700">
          {count}
        </span>
      )}
      {collapsed && typeof count === "number" && count > 0 && (
        <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-brand-500" />
      )}
    </Link>
  );
}

function NavGroupBlock({
  group,
  activeNav,
  counts,
  collapsed,
}: {
  group: NavGroup;
  activeNav: NavKey;
  counts?: SidebarProps["counts"];
  collapsed: boolean;
}) {
  return (
    <div className="space-y-0.5">
      {group.heading && !collapsed && (
        <div className="px-2.5 pb-1 pt-3 text-caption uppercase tracking-wide text-ink-tertiary">
          {group.heading}
        </div>
      )}
      {group.heading && collapsed && <div className="pt-3" />}
      {group.items.map((item) => (
        <NavRow
          key={item.key}
          item={item}
          active={item.key === activeNav}
          count={item.countKey ? counts?.[item.countKey] : undefined}
          collapsed={collapsed}
        />
      ))}
    </div>
  );
}

export function Sidebar({
  mode,
  activeNav,
  tenant,
  user,
  project,
  otherProjects = [],
  counts,
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

  const groups =
    mode === "project" && project
      ? projectNavGroups(project.id)
      : homeNavGroups();

  const canManageUsers =
    Boolean(user.isSuperAdmin) ||
    ["tenant_admin", "admin", "root_admin"].includes(user.rawRole ?? "");
  const isPlatformAdmin =
    Boolean(user.isSuperAdmin) || user.rawRole === "root_admin";

  const adminItems: NavItem[] = canManageUsers
    ? [
        {
          key: "admin-users",
          label: "Users",
          href: "/admin/users",
          icon: IconUsers,
        },
        {
          key: "admin-tenants",
          label: isPlatformAdmin ? "Tenants" : "My Tenant",
          href: "/admin/tenants",
          icon: IconBuildingBank,
        },
        {
          key: "admin-allowed-domains",
          label: "Allowed Domains",
          href: "/admin/allowed-domains",
          icon: IconShieldLock,
        },
        {
          key: "admin-data-source-assignments",
          label: "Data Source Assignments",
          href: "/admin/data-source-assignments",
          icon: IconDatabaseShare,
        },
        {
          key: "admin-branding",
          label: "Branding",
          href: "/admin/branding",
          icon: IconPhoto,
        },
        {
          key: "admin-analytical-methods",
          label: "Analytical Methods",
          href: "/admin/analytical-methods",
          icon: IconMathFunction,
        },
        {
          key: "admin-ai-governance",
          label: "AI Governance",
          href: "/admin/ai-governance",
          icon: IconBrain,
        },
      ]
    : [];

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r border-line-tertiary bg-bg-primary transition-[width] duration-200",
        collapsed ? "w-14" : "w-sidebar",
      )}
    >
      {collapsed ? (
        <div className="flex flex-col items-center gap-1 px-2 py-3">
          <Link
            href="/"
            title="Tablescope home"
            className="transition-opacity hover:opacity-80"
          >
            <BrandMark />
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
            className="flex min-w-0 flex-1 items-center gap-2 transition-opacity hover:opacity-80"
          >
            <BrandMark />
            <span className="truncate text-h2 text-ink-primary">Tablescope</span>
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
        {groups.map((group, i) => (
          <NavGroupBlock
            key={group.heading ?? `g${i}`}
            group={group}
            activeNav={activeNav}
            counts={counts}
            collapsed={collapsed}
          />
        ))}

        {mode === "home" && adminItems.length > 0 && (
          <NavGroupBlock
            group={{ heading: "Administration", items: adminItems }}
            activeNav={activeNav}
            collapsed={collapsed}
          />
        )}

        {mode === "project" && otherProjects.length > 0 && (
          <div className="space-y-0.5">
            {!collapsed && (
              <div className="px-2.5 pb-1 pt-3 text-caption uppercase tracking-wide text-ink-tertiary">
                Other Projects
              </div>
            )}
            {collapsed && <div className="pt-3" />}
            {otherProjects.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                title={collapsed ? p.name : undefined}
                className={cn(
                  "flex items-center rounded-md text-[13px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary",
                  collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-2.5 py-1.5",
                )}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: p.accent ?? accentFor(p.id) }}
                />
                {!collapsed && <span className="flex-1 truncate">{p.name}</span>}
              </Link>
            ))}
            <Link
              href="/projects?new=1"
              title={collapsed ? "New project" : undefined}
              className={cn(
                "flex items-center rounded-md text-[13px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary",
                collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-2.5 py-1.5",
              )}
            >
              <IconPlus size={15} stroke={1.8} className="shrink-0" />
              {!collapsed && <span>New project</span>}
            </Link>
          </div>
        )}
      </nav>

      <AccountMenu user={user} collapsed={collapsed} />
    </aside>
  );
}

function AccountMenu({
  user,
  collapsed,
}: {
  user: CurrentUser;
  collapsed: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative flex items-center border-t border-line-tertiary py-3",
        collapsed ? "flex-col gap-1 px-2" : "gap-2.5 px-3",
      )}
    >
      <AvatarUploader user={user} />
      {collapsed ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={open}
          title={`${user.name} · account menu`}
          className="flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
        >
          <IconChevronDown
            size={14}
            className={cn("transition-transform", open && "rotate-180")}
          />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-bg-secondary"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-ink-primary">
              {user.name}
            </span>
            <span className="block truncate text-caption text-ink-tertiary">
              {user.role} · {user.tenantName}
            </span>
          </span>
          <IconChevronDown
            size={14}
            className={cn(
              "shrink-0 text-ink-tertiary transition-transform",
              open && "rotate-180",
            )}
          />
        </button>
      )}

      {open && (
        <div
          role="menu"
          className={cn(
            "absolute bottom-[calc(100%-4px)] z-20 overflow-hidden rounded-md border border-line-secondary bg-bg-primary py-1 shadow-lg",
            collapsed ? "left-2 w-48" : "left-3 right-3",
          )}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              router.push("/profile");
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconUserCircle size={16} className="shrink-0" />
            Profile
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              signOut();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-danger hover:bg-danger/5"
          >
            <IconLogout size={16} className="shrink-0" />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

const ACCEPTED_AVATAR_TYPES = "image/png,image/jpeg,image/webp";
const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

function AvatarUploader({ user }: { user: CurrentUser }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAvatarSelected(
    e: React.ChangeEvent<HTMLInputElement>,
  ) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > MAX_AVATAR_BYTES) {
      setError("Image too large (max 5 MB).");
      return;
    }
    setError(null);
    setUploading(true);
    try {
      await apiClient.upload("/api/users/me/avatar", file);
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      <input
        type="file"
        accept={ACCEPTED_AVATAR_TYPES}
        className="hidden"
        ref={fileInputRef}
        onChange={handleAvatarSelected}
        aria-hidden="true"
        tabIndex={-1}
      />
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={uploading}
        title={error ?? "Change profile picture"}
        aria-label="Change profile picture"
        className="group relative flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700 ring-offset-1 hover:ring-2 hover:ring-brand-200 disabled:opacity-60"
      >
        {user.avatarUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={user.avatarUrl}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <span>{user.initials}</span>
        )}
        {uploading && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/40 text-[9px] text-white">
            …
          </span>
        )}
      </button>
    </>
  );
}
