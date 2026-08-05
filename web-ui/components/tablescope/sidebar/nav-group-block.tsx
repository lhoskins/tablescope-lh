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
} from "../nav";import { SidebarProps } from "./sidebar-props";
import { NavRow } from "./nav-row";



export function NavGroupBlock({
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