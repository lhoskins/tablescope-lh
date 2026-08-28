"use client";

import { useCallback, useEffect, useState } from "react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { getUserMeta } from "@/lib/auth";
import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  publishWorkspace,
  unpublishWorkspace,
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
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const currentUserId = getUserMeta()?.user_id ?? null;

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
  const isOwner = active != null && active.owner_user_id === currentUserId;

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

  const onRename = useCallback(
    async (workspaceId: number, name: string) => {
      const previous = workspaces.find((w) => w.id === workspaceId);
      if (!previous) return;
      setWorkspaces((prev) => prev.map((w) => (w.id === workspaceId ? { ...w, name } : w)));
      try {
        const saved = await updateWorkspace(projectId, workspaceId, { name });
        setWorkspaces((prev) => prev.map((w) => (w.id === saved.id ? saved : w)));
      } catch (err) {
        setWorkspaces((prev) => prev.map((w) => (w.id === previous.id ? previous : w)));
        setError(err instanceof Error ? err.message : "Could not rename the workspace.");
      }
    },
    [projectId, workspaces],
  );

  const onPublish = useCallback(
    async (workspaceId: number) => {
      try {
        const saved = await publishWorkspace(projectId, workspaceId);
        setWorkspaces((prev) => prev.map((w) => (w.id === saved.id ? saved : w)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not publish the workspace.");
      }
    },
    [projectId],
  );

  const onUnpublish = useCallback(
    async (workspaceId: number) => {
      try {
        const saved = await unpublishWorkspace(projectId, workspaceId);
        setWorkspaces((prev) => prev.map((w) => (w.id === saved.id ? saved : w)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not unpublish the workspace.");
      }
    },
    [projectId],
  );

  const requestDelete = useCallback((workspaceId: number) => {
    setPendingDeleteId(workspaceId);
  }, []);

  const confirmDelete = useCallback(async () => {
    const workspaceId = pendingDeleteId;
    setPendingDeleteId(null);
    if (workspaceId == null) return;
    try {
      await deleteWorkspace(projectId, workspaceId);
      setWorkspaces((prev) => {
        const next = prev.filter((w) => w.id !== workspaceId);
        setActiveId((current) => (current === workspaceId ? next[0]?.id ?? null : current));
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the workspace.");
    }
  }, [pendingDeleteId, projectId]);

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
          currentUserId={currentUserId}
          onRename={(id, name) => void onRename(id, name)}
          onPublish={(id) => void onPublish(id)}
          onUnpublish={(id) => void onUnpublish(id)}
          onDelete={requestDelete}
        />
        <ConfirmDialog
          open={pendingDeleteId != null}
          title="Delete workspace?"
          message="This removes the workspace and its pinned cards. This can't be undone."
          confirmLabel="Delete"
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDeleteId(null)}
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
