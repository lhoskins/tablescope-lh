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
} from "@/lib/api/project-actions";import { formatDateShort } from "./format-date-short";



export function InlineDate({
  value,
  canEdit,
  onChange,
}: {
  value: string | null;
  canEdit: boolean;
  onChange: (v: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value) || "mm/dd/yyyy";
  if (canEdit && editing) {
    return (
      <input
        type="date"
        value={value ? value.split("T")[0] : ""}
        onChange={(e) => onChange(e.target.value || null)}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
        autoFocus
        className="rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-[12px] text-ink-primary outline-none focus:border-brand-500"
      />
    );
  }
  return (
    <button
      type="button"
      disabled={!canEdit}
      onClick={() => setEditing(true)}
      className="truncate rounded px-1 py-0.5 text-left text-[12px] text-ink-secondary disabled:cursor-default disabled:hover:bg-transparent hover:bg-bg-secondary"
    >
      {display}
    </button>
  );
}