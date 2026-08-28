"use client";

import { useMemo, useState } from "react";
import { IconPlus } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import {
  useProjectDashboards,
  useProjectDocuments,
  useProjectQueries,
} from "@/lib/ui/use-project-data";
import type { WorkspaceCard } from "@/lib/api/workspaces";
import type { WorkspaceResourceType } from "./workspace-tabs-storage";

export interface AddableResource {
  resource_type: WorkspaceResourceType;
  resource_id: string;
  label: string;
}

/** The project's tables/dashboards/documents, flagged with whether they are
 *  already pinned in the active workspace — the same membership state the
 *  sidebar asset tree highlights. */
export function useAddableResources(
  projectId: string,
  cards: WorkspaceCard[],
): { resources: AddableResource[]; isPinned: (r: AddableResource) => boolean } {
  const { data: queries } = useProjectQueries(projectId);
  const { data: dashboards } = useProjectDashboards(projectId);
  const { data: documents } = useProjectDocuments(projectId);

  const resources = useMemo<AddableResource[]>(
    () => [
      ...(queries ?? []).map((q) => ({
        resource_type: "table" as const,
        resource_id: String(q.id),
        label: q.name,
      })),
      ...(dashboards ?? []).map((d) => ({
        resource_type: "dashboard" as const,
        resource_id: String(d.id),
        label: d.name,
      })),
      ...(documents ?? []).map((d) => ({
        resource_type: "document" as const,
        resource_id: String(d.id),
        label: d.title,
      })),
    ],
    [queries, dashboards, documents],
  );

  const pinned = useMemo(
    () => new Set(cards.map((c) => `${c.resource_type}:${c.resource_id}`)),
    [cards],
  );

  return {
    resources,
    isPinned: (r) => pinned.has(`${r.resource_type}:${r.resource_id}`),
  };
}

export function WorkspaceAddCard({
  projectId,
  cards,
  onAdd,
}: {
  projectId: string;
  cards: WorkspaceCard[];
  onAdd: (resource: AddableResource) => void;
}) {
  const [open, setOpen] = useState(false);
  const { resources, isPinned } = useAddableResources(projectId, cards);

  return (
    <div className="px-5 pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-[12px] font-medium text-ink-secondary hover:bg-bg-secondary"
      >
        <IconPlus size={13} /> Add card
      </button>
      {open && (
        <ul aria-label="Add a resource to this workspace" className="mt-2 max-h-64 overflow-y-auto rounded-md border border-line-tertiary">
          {resources.length === 0 && (
            <li className="px-3 py-2 text-[12px] text-ink-tertiary">
              This project has no tables, dashboards or documents yet.
            </li>
          )}
          {resources.map((resource) => {
            const pinned = isPinned(resource);
            return (
              <li key={`${resource.resource_type}:${resource.resource_id}`}>
                <button
                  type="button"
                  disabled={pinned}
                  onClick={() => {
                    onAdd(resource);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12px]",
                    pinned
                      ? "cursor-default font-medium text-brand-600"
                      : "text-ink-secondary hover:bg-bg-secondary",
                  )}
                >
                  <span className="truncate">{resource.label}</span>
                  <span className="shrink-0 text-ink-tertiary">
                    {pinned ? "In workspace" : resource.resource_type.replace("_", " ")}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
