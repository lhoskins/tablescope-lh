"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import {
  IconChevronDown,
  IconPlus,
  IconUsers,
  IconBuildingBank,
  IconShieldLock,
  IconDatabaseShare,
} from "@tabler/icons-react";
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
}: {
  item: NavItem;
  active: boolean;
  count?: number;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px]",
        active
          ? "bg-brand-50 font-semibold text-brand-500"
          : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
      )}
    >
      <Icon size={15} stroke={1.8} className="shrink-0" />
      <span className="flex-1 truncate">{item.label}</span>
      {typeof count === "number" && count > 0 && (
        <span className="rounded-full bg-brand-50 px-1.5 text-[11px] font-medium text-brand-700">
          {count}
        </span>
      )}
    </Link>
  );
}

function NavGroupBlock({
  group,
  activeNav,
  counts,
}: {
  group: NavGroup;
  activeNav: NavKey;
  counts?: SidebarProps["counts"];
}) {
  return (
    <div className="space-y-0.5">
      {group.heading && (
        <div className="px-2.5 pb-1 pt-3 text-caption uppercase tracking-wide text-ink-tertiary">
          {group.heading}
        </div>
      )}
      {group.items.map((item) => (
        <NavRow
          key={item.key}
          item={item}
          active={item.key === activeNav}
          count={item.countKey ? counts?.[item.countKey] : undefined}
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
      ]
    : [];

  return (
    <aside className="flex w-sidebar shrink-0 flex-col border-r border-line-tertiary bg-bg-primary">
      <Link
        href="/"
        className="flex items-center gap-2 px-4 py-3.5 transition-opacity hover:opacity-80"
      >
        <BrandMark />
        <span className="text-h2 text-ink-primary">Tablescope</span>
      </Link>

      {/* Selector pill */}
      <div className="px-3 pb-2">
        {mode === "project" && project ? (
          <Link
            href={`/projects/${project.id}`}
            className="flex items-center gap-2 rounded-md border border-line-secondary px-2.5 py-2 text-[13px] font-medium text-ink-primary hover:bg-bg-secondary"
          >
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: project.accent ?? accentFor(project.id) }}
            />
            <span className="flex-1 truncate">{project.name}</span>
            <IconChevronDown size={14} className="text-ink-tertiary" />
          </Link>
        ) : (
          <div className="flex items-center gap-2 rounded-md border border-line-secondary px-2.5 py-2">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand-50 text-[10px] font-semibold text-brand-700">
              {tenant.initials}
            </span>
            <span className="flex-1 truncate text-[13px] font-medium text-ink-primary">
              {tenant.name}
            </span>
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 pb-4">
        {groups.map((group, i) => (
          <NavGroupBlock
            key={group.heading ?? `g${i}`}
            group={group}
            activeNav={activeNav}
            counts={counts}
          />
        ))}

        {mode === "home" && adminItems.length > 0 && (
          <NavGroupBlock
            group={{ heading: "Administration", items: adminItems }}
            activeNav={activeNav}
          />
        )}

        {mode === "project" && otherProjects.length > 0 && (
          <div className="space-y-0.5">
            <div className="px-2.5 pb-1 pt-3 text-caption uppercase tracking-wide text-ink-tertiary">
              Other Projects
            </div>
            {otherProjects.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: p.accent ?? accentFor(p.id) }}
                />
                <span className="flex-1 truncate">{p.name}</span>
              </Link>
            ))}
            <Link
              href="/projects?new=1"
              className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              <IconPlus size={15} stroke={1.8} />
              <span>New project</span>
            </Link>
          </div>
        )}
      </nav>

      <div className="flex items-center gap-2.5 border-t border-line-tertiary px-3 py-3">
        <AvatarUploader user={user} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-ink-primary">
            {user.name}
          </div>
          <div className="truncate text-caption text-ink-tertiary">
            {user.role} · {user.tenantName}
          </div>
        </div>
      </div>
    </aside>
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
