export const ASSISTANT_WIDTH_KEY = "tablescope:workspace-assistant-width";
export const ASSISTANT_COLLAPSED_KEY = "tablescope:workspace-assistant-collapsed";

export const ASSISTANT_MIN_WIDTH = 280;
export const ASSISTANT_MAX_WIDTH = 560;
export const ASSISTANT_DEFAULT_WIDTH = 360;

export function clampAssistantWidth(width: number): number {
  return Math.min(ASSISTANT_MAX_WIDTH, Math.max(ASSISTANT_MIN_WIDTH, width));
}

export function loadAssistantWidth(): number {
  if (typeof window === "undefined") return ASSISTANT_DEFAULT_WIDTH;
  try {
    const raw = window.localStorage.getItem(ASSISTANT_WIDTH_KEY);
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? clampAssistantWidth(parsed) : ASSISTANT_DEFAULT_WIDTH;
  } catch {
    return ASSISTANT_DEFAULT_WIDTH;
  }
}

export function saveAssistantWidth(width: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ASSISTANT_WIDTH_KEY, String(clampAssistantWidth(width)));
  } catch {
    // Storage may be unavailable -- the width just won't persist.
  }
}

/** Defaults to collapsed: an unopened panel should never cost a network
 *  round trip, and most project pages (Tables, Data Sources, ...) are
 *  navigated far more often than the assistant is actually used. */
export function loadAssistantCollapsed(fallback: boolean = true): boolean {
  if (typeof window === "undefined") return fallback;
  try {
    const stored = window.localStorage.getItem(ASSISTANT_COLLAPSED_KEY);
    return stored === null ? fallback : stored === "true";
  } catch {
    return fallback;
  }
}

export function saveAssistantCollapsed(collapsed: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ASSISTANT_COLLAPSED_KEY, String(collapsed));
  } catch {
    // Storage may be unavailable -- the collapsed state just won't persist.
  }
}
