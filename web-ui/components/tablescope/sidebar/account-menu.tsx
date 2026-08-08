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
} from "../nav";import { AvatarUploader } from "./avatar-uploader";



export function AccountMenu({
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