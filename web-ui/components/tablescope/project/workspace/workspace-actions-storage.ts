/**
 * Draft actions captured in a workspace, before anything is committed to
 * Project Actions.
 *
 * This is deliberately a scratchpad: you note what you want done while looking
 * at the data, and only the ones worth keeping get promoted into the real
 * project-actions API later. That's why it's localStorage and keyed per
 * workspace (same scheme as workspace notes) rather than a backend table --
 * a half-formed thought shouldn't show up on the project's action board.
 */

export interface DraftAction {
  id: number;
  projectId: string;
  workspaceId: number;
  text: string;
  /** Set when the AI proposed it rather than the user typing it. */
  suggested?: boolean;
  done: boolean;
  createdAt: string;
}

export function workspaceActionsKey(projectId: string, workspaceId: number): string {
  return `tablescope-workspace-actions-${projectId}-${workspaceId}`;
}

function isDraftAction(value: unknown): value is DraftAction {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "number" && typeof v.text === "string";
}

export function loadDraftActions(projectId: string, workspaceId: number): DraftAction[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(workspaceActionsKey(projectId, workspaceId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isDraftAction) : [];
  } catch {
    return [];
  }
}

export function saveDraftActions(
  projectId: string,
  workspaceId: number,
  actions: DraftAction[],
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      workspaceActionsKey(projectId, workspaceId),
      JSON.stringify(actions),
    );
  } catch {
    // Storage may be unavailable -- drafts just won't survive a reload.
  }
}

/** Ids are per-workspace counters, so derive the next one from what's stored. */
export function nextDraftActionId(actions: DraftAction[]): number {
  return actions.reduce((max, action) => Math.max(max, action.id), 0) + 1;
}
