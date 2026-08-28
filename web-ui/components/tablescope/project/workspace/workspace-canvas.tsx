"use client";

import type { UpdateWorkspaceRequest, Workspace, WorkspaceCard as WorkspaceCardModel, WorkspaceCardViewMode } from "@/lib/api/workspaces";
import { WorkspaceCard } from "./workspace-card";

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
  onCardsChange,
}: {
  workspace: Workspace | null;
  editable: boolean;
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
      <p className="px-5 py-8 text-[13px] text-ink-tertiary">
        This workspace is empty. Open a table, dashboard or document to add it as a card.
      </p>
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
    <div
      aria-label={`${workspace.name} canvas`}
      className="grid grid-cols-1 gap-3 px-5 py-4 md:grid-cols-2 xl:grid-cols-3"
    >
      {cards.map((card) => (
        <WorkspaceCard
          key={card.id}
          card={card}
          editable={editable}
          onViewModeChange={(mode) => setViewMode(card, mode)}
          onRemove={() => remove(card)}
          onMove={(direction) => move(card, direction)}
        />
      ))}
    </div>
  );
}
