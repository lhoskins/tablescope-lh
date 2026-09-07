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
import { WorkspaceActionsPane } from "./workspace-actions-pane";
import { WorkspaceFilesPane } from "./workspace-files-pane";
import { WorkspaceAddCard, type AddableResource } from "./workspace-add-card";
import { toCardPatch } from "./workspace-canvas";
import { PaneViewsToggle, WorkspacePanes, type PaneSpec } from "./workspace-panes";
import { usePaneLayout } from "./use-pane-layout";
import { WorkspaceTabBar } from "./workspace-tab-bar";

/** A dead network request surfaces as the browser's own wording -- "Load
 *  failed" in Safari, "Failed to fetch" in Chrome -- which tells the user
 *  nothing about what failed. Swap those for something actionable and keep any
 *  message the API itself bothered to send. */
function friendlyError(err: unknown, fallback: string): string {
  const message = err instanceof Error ? err.message.trim() : "";
  if (!message || /^(load failed|failed to fetch|networkerror.*)$/i.test(message)) {
    return fallback;
  }
  return message;
}

/** Stand-in for drawer content until the metadata and chat panes land. */
function DrawerPlaceholder({ text }: { text: string }) {
  return (
    <p className="px-3 py-4 text-center text-[12px] leading-relaxed text-ink-tertiary">
      {text}
    </p>
  );
}

export function WorkspaceScreen({ projectId }: { projectId: string }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const currentUserId = getUserMeta()?.user_id ?? null;
  // Owned here rather than inside WorkspacePanes: the Pane Views swatches sit
  // up in the workspace tab bar and toggle the same layout the panes read.
  const paneLayout = usePaneLayout(projectId);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const list = await listWorkspaces(projectId);
        if (cancelled) return;
        setWorkspaces(list);
        setActiveId((current) => current ?? list[0]?.id ?? null);
      } catch (err) {
        if (!cancelled) {
          setError(
            friendlyError(err, "Couldn't load workspaces. Is the API running?"),
          );
        }
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
      setError(friendlyError(err, "Could not create the workspace."));
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
        setError(friendlyError(err, "Could not save the workspace."));
      }
    },
    [active, projectId],
  );

  const onAdd = useCallback(
    (resource: AddableResource) => {
      if (!active) return;
      // Dropping the same resource twice is easy to do by accident, and the
      // second card would be an exact duplicate of the first.
      const alreadyPinned = active.cards.some(
        (card) =>
          card.resource_type === resource.resource_type &&
          card.resource_id === resource.resource_id,
      );
      if (alreadyPinned) return;
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
        setError(friendlyError(err, "Could not rename the workspace."));
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
        setError(friendlyError(err, "Could not publish the workspace."));
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
        setError(friendlyError(err, "Could not unpublish the workspace."));
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
      setError(friendlyError(err, "Could not delete the workspace."));
    }
  }, [pendingDeleteId, projectId]);

  const panes: PaneSpec[] = [
    {
      id: "files",
      title: "Documents",
      // "+ Add card" belongs in the pane's menu bar, not above the cards where
      // it pushed the list down.
      actions:
        active && isOwner ? (
          <WorkspaceAddCard projectId={projectId} cards={active.cards} onAdd={onAdd} />
        ) : undefined,
      body: (
        <WorkspaceFilesPane
          workspace={active}
          editable={isOwner}
          // Errors live inside the pane: as a block above the row they shoved
          // all the panes down the screen.
          error={error}
          onAdd={onAdd}
          onCardsChange={(cards) => void onCardsChange(cards)}
        />
      ),
      info: <DrawerPlaceholder text="Metadata for the selected document appears here." />,
      chat: <DrawerPlaceholder text="Ask about the documents in this workspace." />,
      onSendChatToPane: () => undefined,
    },
    {
      id: "preview",
      title: "Preview",
      body: (
        <p className="flex flex-1 items-center justify-center px-5 text-center text-[12px] leading-relaxed text-ink-tertiary">
          Select a document or table in Documents
          <br />
          to preview it here.
        </p>
      ),
      info: <DrawerPlaceholder text="Metadata for the previewed item appears here." />,
      chat: <DrawerPlaceholder text="Ask about the item shown in Preview." />,
      onSendChatToPane: () => undefined,
    },
    {
      id: "chat",
      title: "Chat",
      body: (
        <p className="flex flex-1 items-center justify-center px-5 text-center text-[12px] leading-relaxed text-ink-tertiary">
          Ask about the documents
          <br />
          loaded into this workspace.
        </p>
      ),
    },
    {
      id: "notes",
      title: "Notes",
      body: (
        <p className="flex flex-1 items-center justify-center px-5 text-center text-[12px] leading-relaxed text-ink-tertiary">
          Select text in any pane
          <br />
          and choose <strong className="font-semibold">→ Notes</strong>.
        </p>
      ),
    },
    {
      id: "actions",
      title: "Actions",
      body: <WorkspaceActionsPane projectId={projectId} workspaceId={activeId} />,
      chat: <DrawerPlaceholder text="Ask the assistant about these actions." />,
      onSendChatToPane: () => undefined,
    },
  ];

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="workspace"
      showResourceTabs={false}
      // The panes own the full height, and the Chat pane carries the chat that
      // used to live in the docked assistant.
      scrollable={false}
      showAssistant={false}
    >
      {/* The shell pads content by 20px on every side. The tab strip is chrome
          rather than content, so it wants to sit closer to the nav above it:
          cancel the horizontal padding entirely and most of the top. */}
      <div className="-mx-5 -mt-3 flex h-full min-h-0 flex-col">
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
          trailing={<PaneViewsToggle layout={paneLayout} panes={panes} />}
        />
        <ConfirmDialog
          open={pendingDeleteId != null}
          title="Delete workspace?"
          message="This removes the workspace and its pinned cards. This can't be undone."
          confirmLabel="Delete"
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDeleteId(null)}
        />
        <div className="flex min-h-0 flex-1 flex-col px-3 py-3">
          <WorkspacePanes layout={paneLayout} panes={panes} />
        </div>
      </div>
    </ProjectShell>
  );
}
