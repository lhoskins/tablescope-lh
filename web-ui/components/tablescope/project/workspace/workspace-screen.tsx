"use client";

import { useCallback, useEffect, useState } from "react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { getUserMeta } from "@/lib/auth";
import {
  createWorkspace,
  listWorkspaces,
  updateWorkspace,
  type Workspace,
  type WorkspaceCard,
} from "@/lib/api/workspaces";
import { WorkspaceAddCard, type AddableResource } from "./workspace-add-card";
import { WorkspaceCanvas, toCardPatch } from "./workspace-canvas";
import { WorkspaceTabBar } from "./workspace-tab-bar";

export function WorkspaceScreen({ projectId }: { projectId: string }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const list = await listWorkspaces(projectId);
        if (cancelled) return;
        setWorkspaces(list);
        setActiveId((current) => current ?? list[0]?.id ?? null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load workspaces.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const active = workspaces.find((w) => w.id === activeId) ?? null;
  const isOwner = active != null && active.owner_user_id === getUserMeta()?.user_id;

  const onCreate = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const created = await createWorkspace(projectId, {
        name: `Workspace ${workspaces.length + 1}`,
      });
      setWorkspaces((prev) => [...prev, created]);
      setActiveId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the workspace.");
    } finally {
      setCreating(false);
    }
  }, [projectId, workspaces.length]);

  const onCardsChange = useCallback(
    async (cards: WorkspaceCard[]) => {
      if (!active) return;
      // Optimistic: the canvas already reflects the new order/view modes, and
      // the server response replaces it with the authoritative card ids.
      const previous = active;
      setWorkspaces((prev) => prev.map((w) => (w.id === active.id ? { ...w, cards } : w)));
      try {
        const saved = await updateWorkspace(projectId, active.id, { cards: toCardPatch(cards) });
        setWorkspaces((prev) => prev.map((w) => (w.id === saved.id ? saved : w)));
      } catch (err) {
        setWorkspaces((prev) => prev.map((w) => (w.id === previous.id ? previous : w)));
        setError(err instanceof Error ? err.message : "Could not save the workspace.");
      }
    },
    [active, projectId],
  );

  const onAdd = useCallback(
    (resource: AddableResource) => {
      if (!active) return;
      const next: WorkspaceCard[] = [
        ...active.cards,
        {
          id: -Date.now(),
          resource_type: resource.resource_type,
          resource_id: resource.resource_id,
          view_mode: "card",
          position: active.cards.length,
          label: resource.label,
        },
      ];
      void onCardsChange(next);
    },
    [active, onCardsChange],
  );

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="workspace"
      showResourceTabs={false}
      assistantDefaultOpen
      assistantWorkspaceCards={active?.cards ?? null}
    >
      <div className="-mx-5 flex flex-col">
        <WorkspaceTabBar
          workspaces={workspaces}
          activeWorkspaceId={activeId}
          onSelect={setActiveId}
          onCreate={() => void onCreate()}
          creating={creating}
        />
        {error && (
          <p className="px-5 pt-3 text-[13px] text-red-700" role="alert">
            {error}
          </p>
        )}
        {active && isOwner && (
          <WorkspaceAddCard projectId={projectId} cards={active.cards} onAdd={onAdd} />
        )}
        <WorkspaceCanvas
          workspace={active}
          editable={isOwner}
          onCardsChange={(cards) => void onCardsChange(cards)}
        />
      </div>
    </ProjectShell>
  );
}
