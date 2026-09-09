import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render, renderHook } from "@testing-library/react";
import { useSelectionCapture } from "./use-selection-capture";

const PANE_TITLES = {
  files: "Documents",
  preview: "Preview",
  chat: "Chat",
  notes: "Notes",
  actions: "Actions",
};

/** Select the text inside `element` the way a user's drag would. */
function selectTextIn(element: HTMLElement) {
  const range = document.createRange();
  range.selectNodeContents(element);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  // jsdom gives ranges a zero rect; the hook only uses it for positioning.
  range.getBoundingClientRect = () =>
    ({ top: 100, left: 40, width: 120, height: 18 }) as DOMRect;
  act(() => {
    document.dispatchEvent(new Event("pointerup"));
  });
}

describe("useSelectionCapture", () => {
  beforeEach(() => {
    window.getSelection()?.removeAllRanges();
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("captures a selection and names the pane it came from", () => {
    const { container } = render(
      <section data-pane="preview">
        <p>Access provisioning during onboarding is manual and slow.</p>
      </section>,
    );
    const { result } = renderHook(() => useSelectionCapture(PANE_TITLES));

    selectTextIn(container.querySelector("p") as HTMLElement);

    expect(result.current.selection?.text).toContain("Access provisioning");
    expect(result.current.selection?.paneLabel).toBe("Preview");
    // Positioned just above the selection, centred horizontally.
    expect(result.current.selection?.top).toBe(100);
    expect(result.current.selection?.left).toBe(100);
  });

  it("labels a selection inside a pane's chat drawer distinctly", () => {
    // Otherwise a snippet taken from a drawer conversation would look as if it
    // came from the document itself.
    const { container } = render(
      <section data-pane="files">
        <div data-pane-drawer="chat">
          <p>The report attributes both incidents to stale credentials.</p>
        </div>
      </section>,
    );
    const { result } = renderHook(() => useSelectionCapture(PANE_TITLES));

    selectTextIn(container.querySelector("p") as HTMLElement);

    expect(result.current.selection?.paneLabel).toBe("Documents chat");
  });

  it("ignores selections outside the pane row", () => {
    // The tab strip, sidebar and top bar are chrome, not workspace content.
    const { container } = render(
      <nav>
        <p>Cost review</p>
      </nav>,
    );
    const { result } = renderHook(() => useSelectionCapture(PANE_TITLES));

    selectTextIn(container.querySelector("p") as HTMLElement);

    expect(result.current.selection).toBeNull();
  });

  it("ignores a click with no selection, and clears on Escape", () => {
    const { container } = render(
      <section data-pane="preview">
        <p>Some findings worth keeping.</p>
      </section>,
    );
    const { result } = renderHook(() => useSelectionCapture(PANE_TITLES));

    // A plain click collapses the selection -- no toolbar.
    act(() => {
      document.dispatchEvent(new Event("pointerup"));
    });
    expect(result.current.selection).toBeNull();

    selectTextIn(container.querySelector("p") as HTMLElement);
    expect(result.current.selection).not.toBeNull();

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(result.current.selection).toBeNull();
  });

  it("drops the selection when the pane scrolls", () => {
    // The stored coordinates are viewport-relative, so after a scroll the
    // toolbar would float somewhere unrelated to the text.
    const { container } = render(
      <section data-pane="preview">
        <p>Mean time to resolution improved 18% quarter over quarter.</p>
      </section>,
    );
    const { result } = renderHook(() => useSelectionCapture(PANE_TITLES));

    selectTextIn(container.querySelector("p") as HTMLElement);
    expect(result.current.selection).not.toBeNull();

    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(result.current.selection).toBeNull();
  });
});
