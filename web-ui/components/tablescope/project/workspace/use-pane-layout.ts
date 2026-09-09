"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  COLLAPSED_PANE_WIDTH,
  DEFAULT_DRAWER_HEIGHT,
  DEFAULT_PANE_LAYOUT,
  MIN_DRAWER_HEIGHT,
  MIN_PANE_BODY_HEIGHT,
  MIN_PANE_WIDTH,
  PANE_DEFAULT_RATIO,
  PANE_GAP_PX,
  PANE_IDS,
  loadPaneLayout,
  savePaneLayout,
  type PaneDrawer,
  type PaneId,
  type PaneLayout,
} from "./workspace-pane-storage";

/** Marks the body while a divider is being dragged (see globals.css). */
const RESIZING_CLASS = "workspace-resizing";

/**
 * Resize / collapse / maximize / reorder for the Workspace's panes.
 *
 * Ported from the YouTube Chat app's `modules/resize.js`, and deliberately
 * keeping the thing that made the original feel instant: **the drag writes to
 * the DOM, not to React**. An earlier version of this hook drove `flexBasis`
 * through state, which meant every pointermove re-rendered all four panes and
 * synchronously wrote localStorage -- the pane visibly lagged the cursor and
 * then snapped. Now a drag mutates `style.flexBasis` inside one rAF per frame
 * and commits to state exactly once, on release.
 *
 * Sizing is also delta-based (`startWidth + (clientX - startX)`) rather than
 * absolute (`clientX - areaLeft`); the handle sits in a negative margin, so an
 * absolute reading disagreed with the pane's real width and jumped on the
 * first move.
 */
export function usePaneLayout(projectId: string) {
  const [layout, setLayout] = useState<PaneLayout>(DEFAULT_PANE_LAYOUT);
  const areaRef = useRef<HTMLDivElement | null>(null);
  const hydratedRef = useRef(false);
  const draggingRef = useRef(false);

  // Hydrate after mount: localStorage doesn't exist during SSR, and reading it
  // in useState's initialiser would desync the first client render.
  useEffect(() => {
    setLayout(loadPaneLayout(projectId));
    hydratedRef.current = true;
  }, [projectId]);

  useEffect(() => {
    if (!hydratedRef.current || draggingRef.current) return;
    savePaneLayout(projectId, layout);
  }, [projectId, layout]);

  const paneEl = useCallback(
    (pane: PaneId) =>
      areaRef.current?.querySelector<HTMLElement>(`[data-pane="${pane}"]`) ?? null,
    [],
  );

  // Whether there is anything left to scroll to in each direction, so the
  // `<` / `>` controls can grey out at the ends instead of sitting permanently
  // active and sometimes doing nothing. Recomputed on scroll and on resize,
  // since dragging a divider or changing the split both move the boundaries.
  const [scrollEdges, setScrollEdges] = useState({ left: false, right: false });

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const measure = () => {
      const maxScroll = area.scrollWidth - area.clientWidth;
      setScrollEdges({
        left: area.scrollLeft > 1,
        // A pixel of slack: fractional layout widths mean scrollLeft rarely
        // lands exactly on the maximum.
        right: area.scrollLeft < maxScroll - 1,
      });
    };
    measure();
    area.addEventListener("scroll", measure, { passive: true });
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    for (const child of Array.from(area.children)) observer.observe(child);
    return () => {
      area.removeEventListener("scroll", measure);
      observer.disconnect();
    };
  }, [layout]);

  const isCollapsed = useCallback(
    (pane: PaneId) => layout.collapsed.includes(pane),
    [layout.collapsed],
  );

  const isVisible = useCallback(
    (pane: PaneId) => !layout.hidden.includes(pane),
    [layout.hidden],
  );

  /**
   * Show or hide a pane from the Pane Views bar. Hiding is not collapsing:
   * a hidden pane leaves the row entirely, where a collapsed one keeps a
   * clickable strip. Re-showing clears any collapse so it can't come back as
   * a strip the user has to click twice to read.
   */
  const togglePaneVisible = useCallback((pane: PaneId) => {
    setLayout((prev) => {
      const hiding = !prev.hidden.includes(pane);
      // Never hide the last one -- an empty workspace has no way back except
      // the Pane Views bar itself, and it looks broken.
      if (hiding && prev.hidden.length >= PANE_IDS.length - 1) return prev;
      return {
        ...prev,
        widths: {},
        hidden: hiding
          ? [...prev.hidden, pane]
          : prev.hidden.filter((p) => p !== pane),
        collapsed: hiding ? prev.collapsed : prev.collapsed.filter((p) => p !== pane),
        maximized: hiding && prev.maximized === pane ? null : prev.maximized,
      };
    });
  }, []);

  const toggleCollapsed = useCallback((pane: PaneId) => {
    setLayout((prev) => ({
      ...prev,
      // Dragged widths go with it -- a leftover pixel width fights the
      // ratio-driven layout collapse applies (the original's
      // clearPaneManualWidths()).
      widths: {},
      maximized: prev.maximized === pane ? null : prev.maximized,
      collapsed: prev.collapsed.includes(pane)
        ? prev.collapsed.filter((p) => p !== pane)
        : [...prev.collapsed, pane],
    }));
  }, []);

  const expand = useCallback((pane: PaneId) => {
    setLayout((prev) =>
      prev.collapsed.includes(pane)
        ? { ...prev, widths: {}, collapsed: prev.collapsed.filter((p) => p !== pane) }
        : prev,
    );
  }, []);

  const toggleMaximized = useCallback((pane: PaneId) => {
    setLayout((prev) => ({
      ...prev,
      widths: {},
      collapsed: prev.maximized === pane ? prev.collapsed : [],
      maximized: prev.maximized === pane ? null : pane,
    }));
  }, []);

  /** Open a pane's drawer, or close it if that mode is already showing. */
  const toggleDrawer = useCallback((pane: PaneId, mode: PaneDrawer) => {
    setLayout((prev) => {
      const drawers = { ...prev.drawers };
      if (drawers[pane] === mode) delete drawers[pane];
      else drawers[pane] = mode;
      return { ...prev, drawers };
    });
  }, []);

  const closeDrawer = useCallback((pane: PaneId) => {
    setLayout((prev) => {
      if (!prev.drawers[pane]) return prev;
      const drawers = { ...prev.drawers };
      delete drawers[pane];
      return { ...prev, drawers };
    });
  }, []);

  const drawerOf = useCallback(
    (pane: PaneId): PaneDrawer | null => layout.drawers[pane] ?? null,
    [layout.drawers],
  );

  const drawerHeight = useCallback(
    (pane: PaneId) => layout.drawerHeights[pane] ?? DEFAULT_DRAWER_HEIGHT,
    [layout.drawerHeights],
  );

  /**
   * Set the viewport split -- how many panes fit across the visible area.
   *
   * Deliberately does not touch `hidden`: which panes belong to the workspace
   * is the Pane Views bar's business. Splitting three ways with five panes
   * loaded means three on screen and two a scroll away, not two switched off.
   * Dragged widths are dropped so the new split actually takes effect.
   */
  const setColumns = useCallback((columns: number) => {
    setLayout((prev) => ({ ...prev, widths: {}, maximized: null, columns }));
  }, []);

  const visiblePanes = layout.order.filter((id) => !layout.hidden.includes(id));

  const reorder = useCallback((from: PaneId, to: PaneId) => {
    setLayout((prev) => {
      const fromIndex = prev.order.indexOf(from);
      const toIndex = prev.order.indexOf(to);
      if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return prev;
      const order = prev.order.slice();
      order.splice(toIndex, 0, ...order.splice(fromIndex, 1));
      return { ...prev, order };
    });
  }, []);

  const nextVisiblePane = useCallback(
    (pane: PaneId): PaneId | undefined => {
      const visible = layout.order.filter((id) => !layout.hidden.includes(id));
      return visible[visible.indexOf(pane) + 1];
    },
    [layout.hidden, layout.order],
  );

  /**
   * Whether the divider to the right of `pane` can be dragged.
   *
   * Only the dividers touching a collapsed pane are dead -- a 36px strip has no
   * width to trade. Collapsing one pane used to disable resizing across the
   * whole row, which left the workspace looking broken.
   */
  const isDividerDisabled = useCallback(
    (pane: PaneId): boolean => {
      if (layout.maximized != null) return true;
      if (isCollapsed(pane)) return true;
      const next = nextVisiblePane(pane);
      return next != null && isCollapsed(next);
    },
    [isCollapsed, layout.maximized, nextVisiblePane],
  );

  /**
   * Drag the divider that sits to the right of `pane`.
   *
   * Only the two panes either side of the handle change: the left one takes the
   * dragged width, the right one absorbs the remainder, so panes further along
   * the row stay put.
   */
  const startColumnResize = useCallback(
    (pane: PaneId, event: React.PointerEvent<HTMLDivElement>) => {
      if (isDividerDisabled(pane)) return;
      const target = paneEl(pane);
      const area = areaRef.current;
      if (!target || !area) return;

      // The pane to the right is the next *visible* one, not simply the next in
      // `order`: a hidden pane isn't in the DOM, so resolving the neighbour
      // from the raw order returned an element that doesn't exist and the drag
      // quietly did nothing.
      const next = nextVisiblePane(pane);
      const neighbour = next ? paneEl(next) : null;
      if (!neighbour) return;

      event.preventDefault();
      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);
      draggingRef.current = true;
      document.body.classList.add(RESIZING_CLASS);

      const startX = event.clientX;
      const startWidth = target.offsetWidth;
      const startNeighbour = neighbour.offsetWidth;
      // The pair's combined width is fixed for the duration of the drag, so
      // clamping one side automatically bounds the other.
      const pairWidth = startWidth + startNeighbour;

      let frame = 0;
      let latest = startWidth;

      const apply = () => {
        frame = 0;
        // Longhands, matching `paneStyle` -- a drag must override the split's
        // calc() basis, and mixing shorthand with longhand invites surprises.
        target.style.flexGrow = "0";
        target.style.flexShrink = "0";
        target.style.flexBasis = `${latest}px`;
        neighbour.style.flexGrow = "0";
        neighbour.style.flexShrink = "0";
        neighbour.style.flexBasis = `${pairWidth - latest}px`;
      };

      const onMove = (moveEvent: PointerEvent) => {
        latest = Math.min(
          Math.max(MIN_PANE_WIDTH, startWidth + (moveEvent.clientX - startX)),
          pairWidth - MIN_PANE_WIDTH,
        );
        // One DOM write per frame; a burst of moves coalesces into the next
        // paint instead of thrashing layout.
        if (!frame) frame = requestAnimationFrame(apply);
      };

      const onUp = () => {
        if (frame) cancelAnimationFrame(frame);
        apply();
        handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        document.body.classList.remove(RESIZING_CLASS);
        draggingRef.current = false;
        // One state update, one persist -- for the whole gesture.
        setLayout((prev) => ({
          ...prev,
          widths: {
            ...prev.widths,
            [pane]: latest,
            ...(next ? { [next]: pairWidth - latest } : {}),
          },
        }));
      };

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    },
    [layout.collapsed.length, layout.maximized, layout.order, paneEl],
  );

  /** Drag the divider between a pane's body and its open drawer. */
  const startDrawerResize = useCallback(
    (paneId: PaneId, event: React.PointerEvent<HTMLDivElement>) => {
      const pane = paneEl(paneId);
      const info = pane?.querySelector<HTMLElement>("[data-pane-drawer]");
      if (!pane || !info) return;

      event.preventDefault();
      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);
      draggingRef.current = true;
      document.body.classList.add(RESIZING_CLASS);

      const startY = event.clientY;
      const startHeight = info.offsetHeight;
      const maxHeight = Math.max(
        MIN_DRAWER_HEIGHT,
        pane.getBoundingClientRect().height - MIN_PANE_BODY_HEIGHT,
      );

      let frame = 0;
      let latest = startHeight;

      const apply = () => {
        frame = 0;
        info.style.height = `${latest}px`;
      };

      const onMove = (moveEvent: PointerEvent) => {
        // Dragging up grows the drawer, so the delta is inverted.
        latest = Math.min(
          Math.max(MIN_DRAWER_HEIGHT, startHeight - (moveEvent.clientY - startY)),
          maxHeight,
        );
        if (!frame) frame = requestAnimationFrame(apply);
      };

      const onUp = () => {
        if (frame) cancelAnimationFrame(frame);
        apply();
        handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        document.body.classList.remove(RESIZING_CLASS);
        draggingRef.current = false;
        setLayout((prev) => ({
          ...prev,
          drawerHeights: { ...prev.drawerHeights, [paneId]: latest },
        }));
      };

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    },
    [paneEl],
  );

  /** Inline flex for a pane, given collapse / maximize / split / dragged width. */
  const paneStyle = useCallback(
    (pane: PaneId): React.CSSProperties => {
      // Longhands rather than the `flex` shorthand throughout: a shorthand
      // carrying a calc() basis is silently dropped by stricter CSS parsers.
      if (layout.maximized) {
        return layout.maximized === pane
          ? { flexGrow: 1, flexShrink: 1, flexBasis: "0%" }
          : { display: "none" };
      }
      if (isCollapsed(pane)) return {};
      // A dragged width always wins -- the split is a starting point, not a cage.
      const width = layout.widths[pane];
      if (width != null) {
        return { flexGrow: 0, flexShrink: 0, flexBasis: `${width}px` };
      }
      // More panes than the split can show: pin each to its share of the
      // visible area so the row overflows and scrolls, rather than squeezing
      // every pane until none of them are readable.
      const expanded = visiblePanes.filter((id) => !layout.collapsed.includes(id));
      if (expanded.length > layout.columns) {
        // Collapsed strips are 36px of fixed furniture; leaving their width in
        // the division made the panes overflow by exactly that much and put a
        // scrollbar on a row that actually fit.
        const collapsedCount = visiblePanes.length - expanded.length;
        const reserved =
          (layout.columns - 1) * PANE_GAP_PX +
          collapsedCount * (COLLAPSED_PANE_WIDTH + PANE_GAP_PX);
        return {
          flexGrow: 0,
          flexShrink: 0,
          flexBasis: `calc((100% - ${reserved}px) / ${layout.columns})`,
        };
      }
      // They all fit, so let them share the space by their natural weighting
      // instead of leaving a gap where the unused columns would have been.
      return { flexGrow: PANE_DEFAULT_RATIO[pane], flexShrink: 1, flexBasis: "0%" };
    },
    [isCollapsed, layout.columns, layout.maximized, layout.widths, visiblePanes.length],
  );

  /**
   * Step the row one split-width sideways. Backs the `<` / `>` controls next to
   * the split presets: with more panes than columns the extra ones are only
   * reachable by scrolling, and a scrollbar alone is too easy to miss.
   */
  const scrollByPane = useCallback(
    (direction: -1 | 1) => {
      const area = areaRef.current;
      if (!area) return;
      const step = area.clientWidth / Math.max(1, layout.columns) + PANE_GAP_PX;
      area.scrollBy({ left: direction * step, behavior: "smooth" });
    },
    [layout.columns],
  );

  return {
    areaRef,
    layout,
    isCollapsed,
    isVisible,
    togglePaneVisible,
    columns: layout.columns,
    setColumns,
    scrollByPane,
    canScrollLeft: scrollEdges.left,
    canScrollRight: scrollEdges.right,
    isMaximized: (pane: PaneId) => layout.maximized === pane,
    isDividerDisabled,
    reorderDisabled: layout.maximized != null,
    toggleCollapsed,
    expand,
    toggleMaximized,
    toggleDrawer,
    closeDrawer,
    drawerOf,
    drawerHeight,
    reorder,
    startColumnResize,
    startDrawerResize,
    paneStyle,
  };
}
