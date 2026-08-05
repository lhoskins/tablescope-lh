"use client";


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { initials, timeAgo } from "@/lib/ui/format";
import { useProjectActionsBoard } from "../hooks/use-project-actions-board";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { useToasts } from "@/components/ui/toast";
import {
  type ProjectActionListItem,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
  type ProjectActionGroupBy,
  type ProjectActionSortBy,
  type ProjectActionView,
  type ProjectAction,
  type ProjectActionFilters,
} from "@/lib/api/project-actions";
import {
  IconPlus,
  IconSearch,
  IconChevronDown,
  IconChevronRight,
  IconMessage,
  IconDotsVertical,
  IconLoader2,
  IconClipboardList,
  IconClock,
  IconTrendingUp,
  IconShieldCheck,
  IconSparkles,
  IconCalendar,
  IconTrash,
} from "@tabler/icons-react";


export function RowMenu({
  projectId,
  item,
  canManage,
  onArchive,
  onRestore,
}: {
  projectId: string;
  item: ProjectActionListItem;
  canManage: boolean;
  onArchive: () => void;
  onRestore: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} className="relative flex items-center justify-center">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label="Action menu"
        className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
      >
        <IconDotsVertical size={16} />
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-10 w-40 rounded-md border border-line-tertiary bg-bg-primary py-1 shadow-md">
          <Link
            href={`/projects/${projectId}/actions/${item.id}`}
            className="block px-3 py-1.5 text-[12px] text-ink-primary hover:bg-bg-secondary"
            onClick={() => setOpen(false)}
          >
            Open details
          </Link>
          {canManage && (
            <>
              {item.archived_at ? (
                <button
                  type="button"
                  onClick={() => {
                    onRestore();
                    setOpen(false);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[12px] text-ink-primary hover:bg-bg-secondary"
                >
                  Restore
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    onArchive();
                    setOpen(false);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[12px] text-danger hover:bg-bg-secondary"
                >
                  Archive
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}