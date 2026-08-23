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

export function loadAssistantCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(ASSISTANT_COLLAPSED_KEY) === "true";
  } catch {
    return false;
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
