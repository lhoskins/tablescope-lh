/**
 * Snippets: passages the user pinned to a workspace as context.
 *
 * Selecting text in any pane offers to send it to the Chat pane or to Notes.
 * A chat snippet stays visible above the composer so that after ten minutes of
 * conversation you can still see *which* part of a document, or which answer,
 * the discussion is anchored to -- and it travels with every question as
 * quoted context.
 *
 * Per workspace, matching notes and draft actions: pinned context belongs to
 * the investigation you assembled it for.
 */

export type SnippetTarget = "chat" | "notes";

export interface WorkspaceSnippet {
  id: number;
  projectId: string;
  workspaceId: number;
  /** Where it came from, e.g. `Preview · Incident Report` or `Documents chat`. */
  label: string;
  text: string;
  /** Optional image data URL, for a pasted or dropped screenshot. */
  image?: string;
  createdAt: string;
}

/** Snippets long enough to need collapsing in the UI. */
export const SNIPPET_CLAMP_CHARS = 220;
/** Matches the backend's per-snippet ceiling (ContextSnippet.text). */
export const SNIPPET_MAX_CHARS = 2000;

export function workspaceSnippetsKey(
  projectId: string,
  workspaceId: number,
  target: SnippetTarget,
): string {
  return `tablescope-workspace-${target}-snippets-${projectId}-${workspaceId}`;
}

function isSnippet(value: unknown): value is WorkspaceSnippet {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "number" && typeof v.text === "string";
}

export function loadSnippets(
  projectId: string,
  workspaceId: number,
  target: SnippetTarget,
): WorkspaceSnippet[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(
      workspaceSnippetsKey(projectId, workspaceId, target),
    );
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isSnippet) : [];
  } catch {
    return [];
  }
}

export function saveSnippets(
  projectId: string,
  workspaceId: number,
  target: SnippetTarget,
  snippets: WorkspaceSnippet[],
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      workspaceSnippetsKey(projectId, workspaceId, target),
      JSON.stringify(snippets),
    );
  } catch {
    // Storage unavailable (or full, which a pasted image can cause): the
    // snippet still works for this session, it just won't survive a reload.
  }
}

export function nextSnippetId(snippets: WorkspaceSnippet[]): number {
  return snippets.reduce((max, s) => Math.max(max, s.id), 0) + 1;
}

/** Trim a captured selection to what the backend will accept. */
export function normalizeSnippetText(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, SNIPPET_MAX_CHARS);
}
