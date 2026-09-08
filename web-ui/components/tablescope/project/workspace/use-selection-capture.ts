"use client";

import { useCallback, useEffect, useState } from "react";

export interface CapturedSelection {
  text: string;
  /** Which pane it came from, for the snippet's source label. */
  paneLabel: string;
  /** Viewport coordinates of the selection, for positioning the toolbar. */
  top: number;
  left: number;
}

/**
 * Watch for text selected inside the workspace panes.
 *
 * Ported from the reference app's selection handling: highlight a passage and a
 * small toolbar appears at the selection offering to keep it. Here it resolves
 * which pane the selection came from (walking up to the nearest `[data-pane]`)
 * so a snippet can say where it came from -- "Preview", "Documents chat" --
 * which is the whole point of pinning it.
 *
 * Selections are read on pointerup/keyup rather than `selectionchange`: the
 * latter fires continuously while dragging, so the toolbar would chase the
 * cursor mid-selection.
 */
export function useSelectionCapture(paneTitles: Record<string, string>) {
  const [selection, setSelection] = useState<CapturedSelection | null>(null);

  const clear = useCallback(() => setSelection(null), []);

  useEffect(() => {
    function read() {
      const active = window.getSelection();
      const text = active?.toString() ?? "";
      if (!active || active.isCollapsed || text.trim().length < 2) {
        setSelection(null);
        return;
      }
      const range = active.getRangeAt(0);
      const node =
        range.commonAncestorContainer.nodeType === Node.TEXT_NODE
          ? range.commonAncestorContainer.parentElement
          : (range.commonAncestorContainer as HTMLElement);
      const pane = node?.closest?.("[data-pane]") as HTMLElement | null;
      // Ignore selections outside the pane row -- the tab strip, the sidebar,
      // anything that isn't workspace content.
      if (!pane?.dataset.pane) {
        setSelection(null);
        return;
      }
      const inDrawer = node?.closest?.("[data-pane-drawer]") != null;
      const paneTitle = paneTitles[pane.dataset.pane] ?? pane.dataset.pane;
      const rect = range.getBoundingClientRect();
      setSelection({
        text,
        paneLabel: inDrawer ? `${paneTitle} chat` : paneTitle,
        // Above the selection, horizontally centred on it.
        top: rect.top,
        left: rect.left + rect.width / 2,
      });
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setSelection(null);
    }

    document.addEventListener("pointerup", read);
    document.addEventListener("keyup", read);
    document.addEventListener("keydown", onKeyDown);
    // Any scroll invalidates the stored coordinates, so drop the toolbar
    // rather than leave it floating somewhere meaningless.
    window.addEventListener("scroll", clear, true);
    window.addEventListener("resize", clear);
    return () => {
      document.removeEventListener("pointerup", read);
      document.removeEventListener("keyup", read);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", clear, true);
      window.removeEventListener("resize", clear);
    };
  }, [clear, paneTitles]);

  return { selection, clear };
}
