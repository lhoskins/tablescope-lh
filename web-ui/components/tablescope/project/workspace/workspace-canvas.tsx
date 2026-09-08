"use client";

import type { UpdateWorkspaceRequest, Workspace, WorkspaceCard as WorkspaceCardModel, WorkspaceCardViewMode } from "@/lib/api/workspaces";
import { WorkspaceCard } from "./workspace-card";
import { PaneEmptyState } from "./pane-empty-state";

/** Rewrite the card list into the full-array shape the PATCH endpoint takes:
 *  adds, removals, reorders and view_mode changes are all the same request. */
export function toCardPatch(cards: WorkspaceCardModel[]): NonNullable<UpdateWorkspaceRequest["cards"]> {
  return cards.map((card, position) => ({
    resource_type: card.resource_type,
    resource_id: card.resource_id,
    view_mode: card.view_mode,
    position,
  }));
}

export function WorkspaceCanvas({
  workspace,
  editable,
  selectedCardId,
  onSelect,
  onCardsChange,
}: {
  workspace: Workspace | null;
  editable: boolean;
  /** `${resource_type}:${resource_id}` of the card showing in Preview. */
  selectedCardId?: string | null;
  onSelect?: (card: WorkspaceCardModel) => void;
  onCardsChange: (cards: WorkspaceCardModel[]) => void;
}) {
  if (!workspace) {
    return (
      <p className="px-5 py-8 text-[13px] text-ink-tertiary">
        Create a workspace to start pinning tables, dashboards and documents to one canvas.
      </p>
    );
  }

  const cards = workspace.cards;

  if (cards.length === 0) {
    return (
      <PaneEmptyState>
        <p className="text-ink-secondary">This workspace is empty.</p>
        <p className="mx-auto mt-3 max-w-md">
          To begin, drag tables, documents or data sources from the left-hand
          sidebar, or use the{" "}
          <span className="whitespace-nowrap">+ Add file</span> button in the
          menu pane.
        </p>
      </PaneEmptyState>
    );
  }

  const setViewMode = (card: WorkspaceCardModel, view_mode: WorkspaceCardViewMode) => {
    onCardsChange(cards.map((c) => (c.id === card.id ? { ...c, view_mode } : c)));
  };

  const remove = (card: WorkspaceCardModel) => {
    onCardsChange(cards.filter((c) => c.id !== card.id));
  };

  const move = (card: WorkspaceCardModel, direction: -1 | 1) => {
    const from = cards.findIndex((c) => c.id === card.id);
    const to = from + direction;
    if (from === -1 || to < 0 || to >= cards.length) return;
    const next = cards.slice();
    [next[from], next[to]] = [next[to], next[from]];
    onCardsChange(next);
  };

  return (
    // Container queries, not viewport breakpoints: these cards live inside a
    // resizable pane, so `md:` / `xl:` measured the wrong thing entirely -- a
    // wide window kept the grid at two or three columns while the pane was
    // dragged down to 240px, and the cards overlapped rather than stacking.
    // `@[...]` reads the pane's own width, so narrowing it stacks the cards.
    // The query container has to be an ancestor of the elements that read it,
    // so the grid sits inside it rather than being it.
    <div className="@container/canvas">
      <div
        aria-label={`${workspace.name} canvas`}
        className="grid grid-cols-1 gap-3 px-3 py-3 @[420px]/canvas:grid-cols-2 @[680px]/canvas:grid-cols-3"
      >
        {cards.map((card) => (
          <WorkspaceCard
            key={card.id}
            card={card}
            editable={editable}
            selected={
              selectedCardId != null &&
              `${card.resource_type}:${card.resource_id}` === selectedCardId
            }
            onSelect={onSelect ? () => onSelect(card) : undefined}
            onViewModeChange={(mode) => setViewMode(card, mode)}
            onRemove={() => remove(card)}
            onMove={(direction) => move(card, direction)}
          />
        ))}
      </div>
    </div>
  );
}
