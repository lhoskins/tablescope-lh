export type WorkspaceResourceType = "table" | "dashboard" | "document" | "data_source";

export interface WorkspaceTab {
  type: WorkspaceResourceType;
  /** Stable key for this tab: a numeric id as a string when the resource has
   *  one, otherwise a resource-specific fallback (e.g. a data source's
   *  lifecycle id). Used for dedup/close, not for backend grounding. */
  id: string;
  /** Numeric resource id, when the resource has a stable one. Sent to the
   *  backend so the AI Assistant can ground its answer on this tab. */
  numericId?: number;
  label: string;
  href: string;
}

export const WORKSPACE_TABS_MAX = 12;

export function workspaceTabsStorageKey(projectId: string): string {
  return `tablescope:workspace-tabs:${projectId}`;
}

function isWorkspaceTab(value: unknown): value is WorkspaceTab {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.type === "string" &&
    typeof v.id === "string" &&
    typeof v.label === "string" &&
    typeof v.href === "string"
  );
}

export function loadWorkspaceTabs(projectId: string): WorkspaceTab[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(workspaceTabsStorageKey(projectId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isWorkspaceTab);
  } catch {
    return [];
  }
}

export function saveWorkspaceTabs(projectId: string, tabs: WorkspaceTab[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      workspaceTabsStorageKey(projectId),
      JSON.stringify(tabs.slice(-WORKSPACE_TABS_MAX)),
    );
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded) -- tabs
    // simply won't persist across reloads, which is a safe degradation.
  }
}

/** Add a newly opened tab at the end, or update an already-open tab's
 *  label/href in place -- switching to a tab that's already open must never
 *  move it, or every click reshuffles the strip out from under the user. */
export function upsertWorkspaceTab(tabs: WorkspaceTab[], tab: WorkspaceTab): WorkspaceTab[] {
  const index = tabs.findIndex((t) => t.type === tab.type && t.id === tab.id);
  if (index !== -1) {
    const next = tabs.slice();
    next[index] = tab;
    return next;
  }
  const next = [...tabs, tab];
  return next.length > WORKSPACE_TABS_MAX
    ? next.slice(next.length - WORKSPACE_TABS_MAX)
    : next;
}

export function closeWorkspaceTab(
  tabs: WorkspaceTab[],
  type: WorkspaceResourceType,
  id: string,
): WorkspaceTab[] {
  return tabs.filter((t) => !(t.type === type && t.id === id));
}
