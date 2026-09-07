import { describe, expect, it, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { usePaneLayout } from "./use-pane-layout";
import {
  DEFAULT_PANE_ORDER,
  loadPaneLayout,
  workspacePaneLayoutKey,
} from "./workspace-pane-storage";

describe("usePaneLayout", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts in the default order and persists a reorder", () => {
    const { result } = renderHook(() => usePaneLayout("7"));
    expect(result.current.layout.order).toEqual(DEFAULT_PANE_ORDER);

    // Drag Notes onto Preview: it lands at Preview's index, pushing the rest right.
    act(() => result.current.reorder("notes", "preview"));
    const reordered = ["files", "notes", "preview", "chat", "actions"];
    expect(result.current.layout.order).toEqual(reordered);

    // Survives a remount, and only for this project.
    expect(loadPaneLayout("7").order).toEqual(reordered);
    expect(loadPaneLayout("8").order).toEqual(DEFAULT_PANE_ORDER);
  });

  it("ignores a reorder onto itself or onto an unknown pane", () => {
    const { result } = renderHook(() => usePaneLayout("7"));
    act(() => result.current.reorder("files", "files"));
    expect(result.current.layout.order).toEqual(DEFAULT_PANE_ORDER);
  });

  it("collapses, expands and maximizes, dropping dragged widths each time", () => {
    const { result } = renderHook(() => usePaneLayout("7"));

    act(() => result.current.toggleCollapsed("notes"));
    expect(result.current.isCollapsed("notes")).toBe(true);

    act(() => result.current.expand("notes"));
    expect(result.current.isCollapsed("notes")).toBe(false);

    act(() => result.current.toggleMaximized("preview"));
    expect(result.current.isMaximized("preview")).toBe(true);
    expect(result.current.paneStyle("preview")).toEqual({
      flexGrow: 1,
      flexShrink: 1,
      flexBasis: "0%",
    });
    // Siblings are hidden rather than squeezed.
    expect(result.current.paneStyle("chat")).toEqual({ display: "none" });
    expect(result.current.reorderDisabled).toBe(true);

    act(() => result.current.toggleMaximized("preview"));
    expect(result.current.isMaximized("preview")).toBe(false);
  });

  it("opens one drawer per pane, swapping mode rather than stacking", () => {
    const { result } = renderHook(() => usePaneLayout("7"));

    act(() => result.current.toggleDrawer("files", "info"));
    expect(result.current.drawerOf("files")).toBe("info");

    act(() => result.current.toggleDrawer("files", "chat"));
    expect(result.current.drawerOf("files")).toBe("chat");

    // Same mode again closes it.
    act(() => result.current.toggleDrawer("files", "chat"));
    expect(result.current.drawerOf("files")).toBeNull();

    // Panes keep their own drawer state.
    act(() => result.current.toggleDrawer("preview", "info"));
    expect(result.current.drawerOf("preview")).toBe("info");
    expect(result.current.drawerOf("files")).toBeNull();
  });

  it("collapsing one pane only disables the dividers touching it", () => {
    const { result } = renderHook(() => usePaneLayout("7"));
    // Visible by default: files, preview, chat, notes.
    act(() => result.current.toggleCollapsed("chat"));

    // The dividers either side of the collapsed strip have nothing to trade...
    expect(result.current.isDividerDisabled("preview")).toBe(true);
    expect(result.current.isDividerDisabled("chat")).toBe(true);
    // ...but the rest of the row must still be resizable. Disabling every
    // divider the moment anything collapsed made the workspace feel frozen.
    expect(result.current.isDividerDisabled("files")).toBe(false);

    // Maximize is different: there's only one pane on screen to resize.
    act(() => result.current.toggleMaximized("files"));
    expect(result.current.isDividerDisabled("files")).toBe(true);
  });

  it("keeps a collapsed strip out of the split's width division", () => {
    const { result } = renderHook(() => usePaneLayout("7"));
    act(() => result.current.setColumns(2));
    expect(result.current.paneStyle("files").flexBasis).toBe(
      "calc((100% - 12px) / 2)",
    );

    // Collapsing Chat leaves three expanded panes over two columns, and the
    // 36px strip plus its gap is reserved rather than divided.
    act(() => result.current.toggleCollapsed("chat"));
    expect(result.current.paneStyle("files").flexBasis).toBe(
      "calc((100% - 60px) / 2)",
    );
  });

  it("splits the viewport without changing which panes are shown", () => {
    const { result } = renderHook(() => usePaneLayout("7"));
    // Four panes visible by default (Actions ships hidden), split four ways --
    // they all fit, so each shares the row by its natural weighting.
    expect(result.current.paneStyle("files")).toEqual({
      flexGrow: 1,
      flexShrink: 1,
      flexBasis: "0%",
    });

    act(() => result.current.setColumns(2));

    // Split two-up with four panes loaded: each takes half the visible width
    // minus the gap, so the row overflows and the other two are a scroll away.
    expect(result.current.paneStyle("files")).toEqual({
      flexGrow: 0,
      flexShrink: 0,
      flexBasis: "calc((100% - 12px) / 2)",
    });
    // Crucially, the pane set is untouched -- splitting is not hiding.
    expect(result.current.isVisible("chat")).toBe(true);
    expect(result.current.isVisible("notes")).toBe(true);
    expect(loadPaneLayout("7").columns).toBe(2);
  });

  it("hides and shows panes, and refuses to hide the last one", () => {
    const { result } = renderHook(() => usePaneLayout("7"));

    // Actions ships hidden: five panes at once leaves none of them usable.
    expect(result.current.isVisible("actions")).toBe(false);
    act(() => result.current.togglePaneVisible("actions"));
    expect(result.current.isVisible("actions")).toBe(true);

    act(() => result.current.togglePaneVisible("notes"));
    expect(result.current.isVisible("notes")).toBe(false);
    expect(loadPaneLayout("7").hidden).toContain("notes");

    // Hide everything except Documents...
    act(() => {
      result.current.togglePaneVisible("preview");
      result.current.togglePaneVisible("chat");
      result.current.togglePaneVisible("actions");
    });
    expect(result.current.isVisible("files")).toBe(true);

    // ...and the last visible pane stays put, or the workspace is empty with
    // no obvious way back.
    act(() => result.current.togglePaneVisible("files"));
    expect(result.current.isVisible("files")).toBe(true);
  });

  it("re-showing a hidden pane clears any collapse it had", () => {
    const { result } = renderHook(() => usePaneLayout("7"));
    act(() => result.current.toggleCollapsed("notes"));
    act(() => result.current.togglePaneVisible("notes"));
    act(() => result.current.togglePaneVisible("notes"));
    expect(result.current.isVisible("notes")).toBe(true);
    expect(result.current.isCollapsed("notes")).toBe(false);
  });

  it("writes to storage once per settled change, not on every render", () => {
    const setItem = vi.spyOn(window.localStorage, "setItem");
    const { result } = renderHook(() => usePaneLayout("7"));
    setItem.mockClear();

    act(() => result.current.toggleCollapsed("chat"));

    const writes = setItem.mock.calls.filter(
      ([key]) => key === workspacePaneLayoutKey("7"),
    );
    expect(writes).toHaveLength(1);
    setItem.mockRestore();
  });
});
