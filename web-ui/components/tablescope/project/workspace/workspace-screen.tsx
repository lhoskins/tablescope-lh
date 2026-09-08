"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IconPinned, IconPinnedOff } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
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
import { WorkspaceCardInfo } from "./workspace-card-info";
import { WorkspaceChat } from "./workspace-chat";
import { SelectionToolbar } from "./selection-toolbar";
import { WorkspaceSnippetList } from "./workspace-snippet-list";
import { useSelectionCapture } from "./use-selection-capture";
import {
  loadSnippets,
  nextSnippetId,
  normalizeSnippetText,
  saveSnippets,
  type SnippetTarget,
  type WorkspaceSnippet,
} from "./workspace-snippet-storage";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";
import { WorkspaceFilesPane } from "./workspace-files-pane";
import { WorkspacePreviewPane } from "./workspace-preview-pane";
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

/** Header toggle for the Chat/Notes panes: hides the Pinned Context panel
 *  without discarding what's pinned or changing what still reaches the
 *  assistant -- a display preference, not a clear. */
function PinnedContextToggle({
  hidden,
  onClick,
}: {
  hidden: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={hidden ? "Show pinned context" : "Hide pinned context"}
      aria-label={hidden ? "Show pinned context" : "Hide pinned context"}
      aria-pressed={!hidden}
      className={cn(
        "flex h-[26px] w-[26px] items-center justify-center rounded border",
        hidden
          ? "border-line-secondary bg-bg-primary text-ink-tertiary hover:bg-brand-50 hover:text-brand-500"
          : "border-brand-500 bg-brand-50 text-brand-500",
      )}
    >
      {hidden ? <IconPinnedOff size={14} /> : <IconPinned size={14} />}
    </button>
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
  // Which card is showing in Preview. Keyed by resource rather than card id so
  // the selection survives the optimistic id swap when cards are saved.
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  // Pinned excerpts, per workspace and per target.
  const [chatSnippets, setChatSnippets] = useState<WorkspaceSnippet[]>([]);
  const [noteSnippets, setNoteSnippets] = useState<WorkspaceSnippet[]>([]);
  // Purely a display toggle -- hides the Pinned Context panel without
  // discarding what's pinned or changing what's sent to the assistant.
  const [chatPinnedHidden, setChatPinnedHidden] = useState(false);
  const [notesPinnedHidden, setNotesPinnedHidden] = useState(false);
  // The live turns of each drawer chat, so ↗ can lift the last exchange.
  const drawerTurns = useRef<Record<string, ConversationTurn[]>>({});

  useEffect(() => {
    if (activeId == null) {
      setChatSnippets([]);
      setNoteSnippets([]);
      return;
    }
    setChatSnippets(loadSnippets(projectId, activeId, "chat"));
    setNoteSnippets(loadSnippets(projectId, activeId, "notes"));
  }, [projectId, activeId]);

  const paneTitles = useMemo(
    () => ({
      files: "Documents",
      preview: "Preview",
      chat: "Chat",
      notes: "Notes",
      actions: "Actions",
    }),
    [],
  );
  const { selection, clear: clearSelection } = useSelectionCapture(paneTitles);

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

  const selectedCard =
    active?.cards.find(
      (card) => `${card.resource_type}:${card.resource_id}` === selectedKey,
    ) ?? null;

  const revealChatPane = useCallback(() => {
    if (!paneLayout.isVisible("chat")) paneLayout.togglePaneVisible("chat");
    if (paneLayout.isCollapsed("chat")) paneLayout.expand("chat");
  }, [paneLayout]);

  const addSnippet = useCallback(
    (target: SnippetTarget, label: string, text: string) => {
      if (activeId == null) return;
      const body = normalizeSnippetText(text);
      if (!body) return;
      const next = [
        ...(target === "chat" ? chatSnippets : noteSnippets),
        {
          id: nextSnippetId(target === "chat" ? chatSnippets : noteSnippets),
          projectId,
          workspaceId: activeId,
          label,
          text: body,
          createdAt: new Date().toISOString(),
        },
      ];
      if (target === "chat") {
        setChatSnippets(next);
        revealChatPane();
      } else {
        setNoteSnippets(next);
        if (!paneLayout.isVisible("notes")) paneLayout.togglePaneVisible("notes");
      }
      saveSnippets(projectId, activeId, target, next);
    },
    [activeId, chatSnippets, noteSnippets, paneLayout, projectId, revealChatPane],
  );

  /** The drawer's ↗: lift that conversation's last exchange into the Chat pane
   *  as a pinned excerpt. The turns themselves already live in the shared
   *  project thread; what this captures is *which* part of a long conversation
   *  the user judged worth keeping. */
  const sendLastExchangeToChat = useCallback(
    (paneTitle: string, turns: ConversationTurn[]) => {
      const last = turns[turns.length - 1];
      if (!last) {
        revealChatPane();
        return;
      }
      const parts = [last.user_message, last.assistant_message]
        .filter((part): part is string => Boolean(part?.trim()))
        .join(" — ");
      addSnippet("chat", `${paneTitle} chat`, parts);
    },
    [addSnippet, revealChatPane],
  );

  const removeSnippet = useCallback(
    (target: SnippetTarget, id: number) => {
      if (activeId == null) return;
      const next = (target === "chat" ? chatSnippets : noteSnippets).filter(
        (s) => s.id !== id,
      );
      if (target === "chat") setChatSnippets(next);
      else setNoteSnippets(next);
      saveSnippets(projectId, activeId, target, next);
    },
    [activeId, chatSnippets, noteSnippets, projectId],
  );

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
          selectedCardId={selectedKey}
          onSelect={(card) => setSelectedKey(`${card.resource_type}:${card.resource_id}`)}
          onAdd={onAdd}
          onCardsChange={(cards) => void onCardsChange(cards)}
        />
      ),
      info: <WorkspaceCardInfo projectId={projectId} card={selectedCard} />,
      chat: (
        <WorkspaceChat
          projectId={projectId}
          cards={active?.cards ?? []}
          focusedCard={selectedCard}
          resume={false}
          onTurnsChange={(turns) => {
            drawerTurns.current.files = turns;
          }}
        />
      ),
      onSendChatToPane: () =>
        sendLastExchangeToChat("Documents", drawerTurns.current.files ?? []),
    },
    {
      id: "preview",
      title: "Preview",
      body: <WorkspacePreviewPane projectId={projectId} card={selectedCard} />,
      info: <WorkspaceCardInfo projectId={projectId} card={selectedCard} />,
      chat: (
        <WorkspaceChat
          projectId={projectId}
          cards={active?.cards ?? []}
          focusedCard={selectedCard}
          resume={false}
          onTurnsChange={(turns) => {
            drawerTurns.current.preview = turns;
          }}
        />
      ),
      onSendChatToPane: () =>
        sendLastExchangeToChat("Preview", drawerTurns.current.preview ?? []),
    },
    {
      id: "chat",
      title: "Chat",
      // The one surface that resumes the project's workspace thread: the
      // drawers show only what was asked in them, this shows the whole history.
      // It also holds the pinned excerpts, which travel with every question.
      actions: (
        <PinnedContextToggle
          hidden={chatPinnedHidden}
          onClick={() => setChatPinnedHidden((v) => !v)}
        />
      ),
      body: (
        <WorkspaceChat
          projectId={projectId}
          cards={active?.cards ?? []}
          focusedCard={selectedCard}
          resume
          snippets={chatSnippets}
          hidePinned={chatPinnedHidden}
          onRemoveSnippet={(id) => removeSnippet("chat", id)}
          onClearSnippets={() => {
            if (activeId == null) return;
            setChatSnippets([]);
            saveSnippets(projectId, activeId, "chat", []);
          }}
        />
      ),
    },
    {
      id: "notes",
      title: "Notes",
      actions: (
        <PinnedContextToggle
          hidden={notesPinnedHidden}
          onClick={() => setNotesPinnedHidden((v) => !v)}
        />
      ),
      body: notesPinnedHidden ? (
        <p className="flex flex-1 items-center justify-center px-5 text-center text-[12px] leading-relaxed text-ink-tertiary">
          Pinned context is hidden.
        </p>
      ) : noteSnippets.length > 0 ? (
        <WorkspaceSnippetList
          snippets={noteSnippets}
          onRemove={(id) => removeSnippet("notes", id)}
          onClear={() => {
            if (activeId == null) return;
            setNoteSnippets([]);
            saveSnippets(projectId, activeId, "notes", []);
          }}
          storageKey="notes"
        />
      ) : (
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
      body: (
        <WorkspaceActionsPane
          projectId={projectId}
          workspaceId={activeId}
          cards={active?.cards ?? []}
          focusedCard={selectedCard}
        />
      ),
      chat: (
        <WorkspaceChat
          projectId={projectId}
          cards={active?.cards ?? []}
          focusedCard={selectedCard}
          resume={false}
        />
      ),
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
        {/* Rendered at the screen level, not inside a pane: a pane clips its
            own overflow, which would cut the toolbar off near an edge. */}
        {selection && activeId != null && (
          <SelectionToolbar
            selection={selection}
            onCopy={() => {
              void navigator.clipboard?.writeText(selection.text);
              clearSelection();
            }}
            onSendToChat={() => {
              addSnippet("chat", selection.paneLabel, selection.text);
              clearSelection();
            }}
            onSendToNotes={() => {
              addSnippet("notes", selection.paneLabel, selection.text);
              clearSelection();
            }}
          />
        )}
      </div>
    </ProjectShell>
  );
}
