import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PaneViewsToggle, WorkspacePanes, type PaneSpec } from "./workspace-panes";
import { usePaneLayout } from "./use-pane-layout";
import { loadPaneLayout } from "./workspace-pane-storage";

/**
 * Note on coverage: dnd-kit's drag itself isn't exercised here. Its sensors
 * resolve drop targets from measured rects, and jsdom reports every element as
 * 0x0, so a simulated drag never finds an `over` no matter how the component
 * is wired -- a passing "drag" test would be theatre. The two halves are
 * covered where they can genuinely fail instead: the activation predicate in
 * `workspace-pane-sensor.test.tsx`, and the resulting state change via
 * `reorder()` in `use-pane-layout.test.tsx`.
 */
const PANES: PaneSpec[] = [
  {
    id: "files",
    title: "Documents",
    body: <p>files body</p>,
    info: <p>doc info</p>,
    chat: <p>doc chat</p>,
  },
  { id: "preview", title: "Preview", body: <p>preview body</p> },
  { id: "chat", title: "Chat", body: <p>chat body</p> },
  { id: "notes", title: "Notes", body: <p>notes body</p> },
  { id: "actions", title: "Actions", body: <p>actions body</p> },
];

/** The screen owns the layout so the tab bar's swatches share it; mirror that
 *  here rather than letting the component own state the real one doesn't. */
function Harness() {
  const layout = usePaneLayout("7");
  return (
    <>
      <PaneViewsToggle layout={layout} panes={PANES} />
      <WorkspacePanes layout={layout} panes={PANES} />
    </>
  );
}

function renderPanes() {
  return render(<Harness />);
}

function paneOrder(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[data-pane]")).map(
    (el) => el.dataset.pane ?? "",
  );
}

describe("WorkspacePanes", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the default panes in order (Chat and Actions ship hidden)", () => {
    renderPanes();
    expect(paneOrder()).toEqual(["files", "preview", "notes"]);
  });

  it("follows a persisted order, appending panes that postdate it", () => {
    // A layout saved before the Actions pane existed. It must keep the user's
    // order and show the new pane rather than hiding it forever.
    window.localStorage.setItem(
      "tablescope:workspace-panes:7",
      JSON.stringify({ order: ["notes", "chat", "preview", "files"] }),
    );
    renderPanes();
    expect(paneOrder()).toEqual(["notes", "chat", "preview", "files", "actions"]);
  });

  it("collapses to a strip labelled with the pane's initial", () => {
    renderPanes();
    fireEvent.click(screen.getByLabelText("Collapse Notes"));

    const expand = screen.getByLabelText("Expand Notes");
    expect(expand.textContent).toBe("N");
    // The body is gone, but the pane keeps its place in the row.
    expect(screen.queryByText("notes body")).toBeNull();
    expect(paneOrder()).toEqual(["files", "preview", "notes"]);

    fireEvent.click(expand);
    expect(screen.getByText("notes body")).toBeTruthy();
  });

  it("only offers info/chat drawers to panes that supply them", () => {
    renderPanes();
    expect(screen.getByLabelText("Documents details")).toBeTruthy();
    expect(screen.getByLabelText("Chat about Documents")).toBeTruthy();
    // Preview passed neither in this fixture; Chat and Notes never get them.
    expect(screen.queryByLabelText("Preview details")).toBeNull();
    expect(screen.queryByLabelText("Chat about Notes")).toBeNull();
  });

  it("swaps drawer modes instead of stacking them, and persists the choice", () => {
    renderPanes();

    fireEvent.click(screen.getByLabelText("Documents details"));
    expect(screen.getByText("doc info")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Chat about Documents"));
    expect(screen.getByText("doc chat")).toBeTruthy();
    expect(screen.queryByText("doc info")).toBeNull();
    expect(loadPaneLayout("7").drawers.files).toBe("chat");

    // The same button again closes it.
    fireEvent.click(screen.getByLabelText("Chat about Documents"));
    expect(screen.queryByText("doc chat")).toBeNull();
    expect(loadPaneLayout("7").drawers.files).toBeUndefined();
  });

  it("Pane Views swatches add and remove panes from the row", () => {
    renderPanes();
    // Actions ships hidden, so its swatch offers to show it.
    expect(paneOrder()).not.toContain("actions");

    fireEvent.click(screen.getByLabelText("Show Actions"));
    expect(paneOrder()).toContain("actions");
    expect(screen.getByText("actions body")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Hide Notes"));
    expect(paneOrder()).not.toContain("notes");
    // Hidden is not collapsed: no strip is left behind to click.
    expect(screen.queryByLabelText("Expand Notes")).toBeNull();
  });

  it("splitting the view never changes which panes are in the workspace", () => {
    renderPanes();
    const before = paneOrder();

    fireEvent.click(screen.getByLabelText("Split into 2"));

    // The split is a viewport concern: every pane the user chose is still
    // mounted, just narrower, with the overflow reachable by scrolling.
    expect(paneOrder()).toEqual(before);
    expect(loadPaneLayout("7").hidden).toEqual(["chat", "actions"]);
    expect(loadPaneLayout("7").columns).toBe(2);
  });

  it("offers the scroll arrows alongside the split presets", () => {
    renderPanes();
    // Nothing to scroll to in jsdom (no layout), so both ends are disabled --
    // which is the behaviour worth pinning: they never sit falsely active.
    expect(screen.getByLabelText("Scroll panes left")).toBeDisabled();
    expect(screen.getByLabelText("Scroll panes right")).toBeDisabled();
  });

  it("maximizing a pane hides its siblings", () => {
    renderPanes();
    fireEvent.click(screen.getByLabelText("Maximize Preview"));

    const preview = document.querySelector<HTMLElement>('[data-pane="preview"]');
    const notes = document.querySelector<HTMLElement>('[data-pane="notes"]');
    expect(preview?.style.display).not.toBe("none");
    expect(notes?.style.display).toBe("none");

    fireEvent.click(screen.getByLabelText("Restore Preview"));
    expect(
      document.querySelector<HTMLElement>('[data-pane="notes"]')?.style.display,
    ).not.toBe("none");
  });
});
