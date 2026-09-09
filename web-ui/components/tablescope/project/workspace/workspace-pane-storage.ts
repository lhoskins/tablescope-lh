/**
 * Persisted geometry for the Workspace screen's four panes.
 *
 * Keyed per project, following `workspace-tabs-storage.ts` -- a project built
 * around a wide table wants a different balance than one that's mostly
 * documents, and that preference shouldn't follow you between them. (The
 * assistant rail's own storage is deliberately global instead; it's one dock,
 * not a per-project layout.)
 *
 * Widths are keyed by pane *id* rather than position, because panes can be
 * reordered -- keying by position would drag each pane's width to whichever
 * pane later occupied that slot.
 */

/** Panes, named for what they hold rather than where they sit. */
export type PaneId = "files" | "preview" | "chat" | "notes" | "actions";

export const PANE_IDS: PaneId[] = ["files", "preview", "chat", "notes", "actions"];

/** Default left-to-right order and the flex ratio each pane starts at. */
export const DEFAULT_PANE_ORDER: PaneId[] = [
  "files",
  "preview",
  "chat",
  "notes",
  "actions",
];
export const PANE_DEFAULT_RATIO: Record<PaneId, number> = {
  files: 1,
  preview: 1.5,
  chat: 1.1,
  notes: 0.9,
  actions: 0.9,
};

/**
 * Which panes a fresh workspace shows. Five panes at once leaves each one too
 * narrow to be useful on a laptop, so a new workspace opens on the reading
 * path -- Documents, Preview, Notes -- and the Pane Views bar brings Chat and
 * Actions in when wanted.
 */
export const DEFAULT_HIDDEN_PANES: PaneId[] = ["chat", "actions"];

/** Selectable split presets. 1 is what maximize is for; 5 is unreadable. */
export const PANE_COLUMN_CHOICES = [2, 3, 4];
export const DEFAULT_PANE_COLUMNS = 3;
/** Must match the `gap-3` between panes, since the split maths subtracts it. */
export const PANE_GAP_PX = 12;

/**
 * A pane's lower drawer. `info` shows the selected item's metadata, `chat` an
 * in-pane conversation about it. One drawer per pane, two modes: opening one
 * replaces the other, so the pane keeps most of its height for content.
 */
export type PaneDrawer = "info" | "chat";

export interface PaneLayout {
  order: PaneId[];
  /** Dragged widths in px. A pane missing here uses its default ratio. */
  widths: Partial<Record<PaneId, number>>;
  /** Panes switched off in the Pane Views bar -- not rendered at all, as
   *  distinct from `collapsed`, which keeps a reopenable strip in the row. */
  hidden: PaneId[];
  /**
   * How many panes fit across the visible area -- the 2/3/4 split presets.
   *
   * Independent of `hidden`: this is the *viewport* split, not the pane set. A
   * workspace can hold five panes and still be split two-up, in which case the
   * row scrolls sideways to reach the rest.
   */
  columns: number;
  collapsed: PaneId[];
  maximized: PaneId | null;
  /** Which drawer, if any, is open per pane. */
  drawers: Partial<Record<PaneId, PaneDrawer>>;
  /** Drawer height in px, per pane. */
  drawerHeights: Partial<Record<PaneId, number>>;
}

/** Matches the reference's MIN_PANE_WIDTH (resize.js). */
export const MIN_PANE_WIDTH = 240;
/** The reference's `flex: 0 0 36px` collapsed strip. */
export const COLLAPSED_PANE_WIDTH = 36;
export const MIN_DRAWER_HEIGHT = 120;
/** How little of the pane body a drawer may leave behind. */
export const MIN_PANE_BODY_HEIGHT = 120;
export const DEFAULT_DRAWER_HEIGHT = 260;

export const DEFAULT_PANE_LAYOUT: PaneLayout = {
  order: DEFAULT_PANE_ORDER,
  widths: {},
  hidden: DEFAULT_HIDDEN_PANES,
  columns: DEFAULT_PANE_COLUMNS,
  collapsed: [],
  maximized: null,
  drawers: {},
  drawerHeights: {},
};

export function workspacePaneLayoutKey(projectId: string): string {
  return `tablescope:workspace-panes:${projectId}`;
}

function isPaneId(value: unknown): value is PaneId {
  return typeof value === "string" && (PANE_IDS as string[]).includes(value);
}

/**
 * Keep every known pane exactly once: drop ids we no longer render, dedupe,
 * and append any pane the stored order predates. Without the backfill, a
 * layout saved before a pane existed would hide that pane permanently.
 */
function normalizeOrder(value: unknown): PaneId[] {
  const stored = Array.isArray(value) ? value.filter(isPaneId) : [];
  const order: PaneId[] = [];
  const seen = new Set<PaneId>();
  for (const id of stored) {
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
  }
  for (const id of DEFAULT_PANE_ORDER) {
    if (!seen.has(id)) order.push(id);
  }
  return order;
}

function normalizeSizes(
  value: unknown,
  min: number,
): Partial<Record<PaneId, number>> {
  if (!value || typeof value !== "object") return {};
  const out: Partial<Record<PaneId, number>> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (!isPaneId(key)) continue;
    if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) {
      out[key] = Math.max(min, raw);
    }
  }
  return out;
}

function normalizeDrawers(value: unknown): Partial<Record<PaneId, PaneDrawer>> {
  if (!value || typeof value !== "object") return {};
  const out: Partial<Record<PaneId, PaneDrawer>> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (isPaneId(key) && (raw === "info" || raw === "chat")) out[key] = raw;
  }
  return out;
}

export function loadPaneLayout(projectId: string): PaneLayout {
  if (typeof window === "undefined") return DEFAULT_PANE_LAYOUT;
  try {
    const raw = window.localStorage.getItem(workspacePaneLayoutKey(projectId));
    if (!raw) return DEFAULT_PANE_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<PaneLayout>;
    if (!parsed || typeof parsed !== "object") return DEFAULT_PANE_LAYOUT;
    return {
      order: normalizeOrder(parsed.order),
      widths: normalizeSizes(parsed.widths, MIN_PANE_WIDTH),
      // A stored layout that predates a pane won't list it as hidden, so new
      // panes appear by default rather than silently staying off.
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden.filter(isPaneId) : [],
      columns: PANE_COLUMN_CHOICES.includes(parsed.columns as number)
        ? (parsed.columns as number)
        : DEFAULT_PANE_COLUMNS,
      collapsed: Array.isArray(parsed.collapsed) ? parsed.collapsed.filter(isPaneId) : [],
      maximized: isPaneId(parsed.maximized) ? parsed.maximized : null,
      drawers: normalizeDrawers(parsed.drawers),
      drawerHeights: normalizeSizes(parsed.drawerHeights, MIN_DRAWER_HEIGHT),
    };
  } catch {
    // Corrupt or unavailable storage -- defaults beat an unrenderable screen.
    return DEFAULT_PANE_LAYOUT;
  }
}

export function savePaneLayout(projectId: string, layout: PaneLayout): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(workspacePaneLayoutKey(projectId), JSON.stringify(layout));
  } catch {
    // Storage may be unavailable -- the layout just won't persist.
  }
}
