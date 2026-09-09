import { describe, expect, it } from "vitest";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { PointerSensorOptions } from "@dnd-kit/core";
import { PaneHeaderPointerSensor } from "./workspace-pane-sensor";

/**
 * The activation predicate decides whether a press on a pane header begins a
 * reorder. Testing it directly rather than through a simulated drag: dnd-kit's
 * pointer/keyboard sensors don't function under jsdom (elements have no
 * geometry, so collision detection never resolves a drop target), and a test
 * that can't fail on real logic is worse than no test.
 */
function press(target: HTMLElement, currentTarget: HTMLElement): boolean {
  const handler = PaneHeaderPointerSensor.activators[0].handler;
  const event = {
    nativeEvent: { target, isPrimary: true, button: 0 },
    currentTarget,
  } as unknown as ReactPointerEvent;
  return handler(event, {} as PointerSensorOptions);
}

describe("PaneHeaderPointerSensor", () => {
  function buildHeader() {
    const header = document.createElement("header");
    // `useSortable` puts role="button" on whatever holds its listeners.
    header.setAttribute("role", "button");
    const title = document.createElement("h2");
    const button = document.createElement("button");
    const noDrag = document.createElement("div");
    noDrag.setAttribute("data-no-drag", "");
    header.append(title, button, noDrag);
    document.body.append(header);
    return { header, title, button, noDrag };
  }

  it("starts a drag from the header itself, despite its role=button", () => {
    const { header } = buildHeader();
    expect(press(header, header)).toBe(true);
  });

  it("starts a drag from plain content inside the header", () => {
    const { header, title } = buildHeader();
    expect(press(title, header)).toBe(true);
  });

  it("leaves header buttons as ordinary clicks", () => {
    const { header, button } = buildHeader();
    expect(press(button, header)).toBe(false);
  });

  it("honours an explicit data-no-drag opt-out", () => {
    const { header, noDrag } = buildHeader();
    expect(press(noDrag, header)).toBe(false);
  });
});
