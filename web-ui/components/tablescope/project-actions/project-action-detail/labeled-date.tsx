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



export function LabeledDate({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value || null) || "mm/dd/yyyy";
  return (
    <div className="space-y-1.5">
      <label className="text-[12px] font-medium text-ink-secondary">{label}</label>
      {editing ? (
        <input
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => setEditing(false)}
          onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
          disabled={disabled}
          autoFocus
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
        />
      ) : (
        <button
          type="button"
          disabled={disabled}
          onClick={() => setEditing(true)}
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-left text-[13px] text-ink-primary disabled:cursor-default disabled:bg-bg-secondary hover:bg-bg-secondary"
        >
          {display}
        </button>
      )}
    </div>
  );
}