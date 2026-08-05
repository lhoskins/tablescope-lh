"use client";


import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import { initials } from "@/lib/ui/format";
import {
  IconLoader2,
  IconPlus,
  IconTrash,
  IconArchive,
  IconSparkles,
  IconChevronDown,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { useToasts } from "@/components/ui/toast";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { canManageProjectActions } from "@/lib/auth";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import {
  projectActionsApi,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
} from "@/lib/api/project-actions";


export function Avatar({ name, size = "sm" }: { name: string; size?: "sm" | "md" }) {
  const sizeClass = size === "sm" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-[11px]";
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-brand-50 font-semibold text-brand-700",
        sizeClass,
      )}
      aria-hidden
    >
      {initials(name || "?")}
    </div>
  );
}