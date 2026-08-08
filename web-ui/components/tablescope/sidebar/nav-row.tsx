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
  projectNavGroups,
  type NavGroup,
  type NavItem,
} from "../nav";


export function NavRow({
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