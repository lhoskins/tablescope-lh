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
} from "../nav";import { ACCEPTED_AVATAR_TYPES } from "./accepted-avatar-types";
import { MAX_AVATAR_BYTES } from "./max-avatar-bytes";



export function AvatarUploader({ user }: { user: CurrentUser }) {
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