"use client";

import type { PointerEvent } from "react";
import { PointerSensor, type PointerSensorOptions } from "@dnd-kit/core";

/**
 * Anything clickable keeps its own behaviour. The whole pane header is the
 * drag activator, so without this a press on Info / maximize / collapse would
 * start dragging the pane instead of pressing the button.
 *
 * Centralised on the sensor rather than an `onPointerDown` guard per button,
 * so a control added to a header later can't silently become a drag handle.
 */
const INTERACTIVE_SELECTOR =
  'button, a, input, select, textarea, [role="button"], [role="switch"], [contenteditable="true"], [data-no-drag]';

export class PaneHeaderPointerSensor extends PointerSensor {
  static activators = [
    {
      eventName: "onPointerDown" as const,
      handler: (event: PointerEvent, options: PointerSensorOptions) => {
        const target = event.nativeEvent.target as HTMLElement | null;
        const interactive = target?.closest?.(INTERACTIVE_SELECTOR) ?? null;
        // The activator node is excluded on purpose. `useSortable` spreads
        // `role="button"` onto whatever carries its listeners, so the header
        // matches the selector above -- without this check the guard rejected
        // every press on the header and no pane could ever be dragged.
        if (interactive && interactive !== event.currentTarget) return false;
        // Otherwise defer to the stock activator, so `onActivation` and the
        // rest of the built-in behaviour still runs.
        return PointerSensor.activators[0].handler(event, options);
      },
    },
  ];
}
