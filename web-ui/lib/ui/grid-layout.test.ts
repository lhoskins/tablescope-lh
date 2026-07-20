import { describe, it, expect } from "vitest";
import {
  getColsForWidth,
  packGridItems,
  buildResponsiveHomeLayouts,
  getPinDefaultSize,
  clampLayoutToCols,
  GRID_BREAKPOINTS,
  GRID_COLS,
} from "./grid-layout";

describe("getColsForWidth", () => {
  it("returns lg for wide screens", () => {
    expect(getColsForWidth(1400, GRID_BREAKPOINTS, GRID_COLS)).toBe(12);
    expect(getColsForWidth(1201, GRID_BREAKPOINTS, GRID_COLS)).toBe(12);
  });

  it("returns md, sm, xs, xxs for smaller screens", () => {
    expect(getColsForWidth(997, GRID_BREAKPOINTS, GRID_COLS)).toBe(10);
    expect(getColsForWidth(769, GRID_BREAKPOINTS, GRID_COLS)).toBe(6);
    expect(getColsForWidth(481, GRID_BREAKPOINTS, GRID_COLS)).toBe(4);
    expect(getColsForWidth(0, GRID_BREAKPOINTS, GRID_COLS)).toBe(2);
  });
});

describe("packGridItems", () => {
  it("preserves saved positions when they fit", () => {
    const items = [
      { id: "a", x: 0, y: 0, w: 3, h: 2 },
      { id: "b", x: 3, y: 0, w: 3, h: 2 },
    ];
    const packed = packGridItems(items, 12);
    expect(packed).toHaveLength(2);
    expect(packed[0]).toMatchObject({ i: "a", x: 0, y: 0, w: 3, h: 2 });
    expect(packed[1]).toMatchObject({ i: "b", x: 3, y: 0, w: 3, h: 2 });
  });

  it("repacks items that overflow the column count", () => {
    const items = [{ id: "a", x: 10, y: 0, w: 6, h: 2 }];
    const packed = packGridItems(items, 12);
    expect(packed[0].x).toBe(0);
    expect(packed[0].y).toBe(0);
    expect(packed[0].w).toBe(6);
  });

  it("repacks colliding items", () => {
    const items = [
      { id: "a", x: 0, y: 0, w: 6, h: 2 },
      { id: "b", x: 2, y: 0, w: 4, h: 2 },
    ];
    const packed = packGridItems(items, 12);
    expect(packed[0]).toMatchObject({ i: "a", x: 0, y: 0 });
    expect(packed[1]).toMatchObject({ i: "b", x: 6, y: 0 });
  });

  it("applies defaults when dimensions are missing", () => {
    const packed = packGridItems([{ id: "a" }], 12, 6, 4);
    expect(packed[0]).toMatchObject({ i: "a", x: 0, y: 0, w: 6, h: 4 });
  });
});

describe("getPinDefaultSize", () => {
  it("uses compact defaults for KPI widgets", () => {
    const pin = {
      id: 1,
      pin_type: "live_widget",
      config: { widget: { type: "kpi" } },
    };
    expect(getPinDefaultSize(pin as any, 12)).toMatchObject({
      w: 3,
      h: 2,
      minW: 2,
      minH: 2,
      maxW: 12,
    });
  });

  it("uses larger defaults for table widgets", () => {
    const pin = {
      id: 2,
      pin_type: "live_widget",
      config: { widget: { type: "table" } },
    };
    expect(getPinDefaultSize(pin as any, 12)).toMatchObject({
      w: 6,
      h: 6,
      minW: 3,
      minH: 4,
    });
  });

  it("uses standard defaults for insight cards", () => {
    const pin = { id: 3, pin_type: "insight_card" };
    expect(getPinDefaultSize(pin as any, 12)).toMatchObject({
      w: 6,
      h: 4,
      minW: 2,
      minH: 2,
    });
  });
});

describe("buildResponsiveHomeLayouts", () => {
  it("builds a desktop layout with four KPIs in one row", () => {
    const pins = Array.from({ length: 4 }).map((_, i) => ({
      id: i + 1,
      pin_type: "live_widget" as const,
      config: { widget: { type: "kpi" } },
      layout: { x: i * 3, y: 0, w: 3, h: 2 },
    }));

    const layouts = buildResponsiveHomeLayouts(pins as any);
    expect(layouts.lg).toHaveLength(4);
    expect(layouts.lg![3]).toMatchObject({ i: "4", x: 9, y: 0, w: 3, h: 2 });
  });

  it("clamps widths for narrow breakpoints without overwriting desktop", () => {
    const pins = [
      {
        id: 1,
        pin_type: "live_widget" as const,
        config: { widget: { type: "kpi" } },
        layout: { x: 0, y: 0, w: 6, h: 2 },
      },
    ];

    const layouts = buildResponsiveHomeLayouts(pins as any);
    expect(layouts.lg![0]).toMatchObject({ i: "1", x: 0, y: 0, w: 6, h: 2 });
    expect(layouts.xxs![0]).toMatchObject({ i: "1", x: 0, y: 0, w: 2, h: 2 });
  });

  it("repacks without overlap when saved positions exceed available columns", () => {
    const pins = [
      {
        id: 1,
        pin_type: "live_widget" as const,
        config: { widget: { type: "kpi" } },
        layout: { x: 0, y: 0, w: 6, h: 2 },
      },
      {
        id: 2,
        pin_type: "live_widget" as const,
        config: { widget: { type: "kpi" } },
        layout: { x: 6, y: 0, w: 6, h: 2 },
      },
    ];

    const layouts = buildResponsiveHomeLayouts(pins as any);
    // xxs has only 2 columns; two 6-wide items must be stacked.
    expect(layouts.xxs![0]).toMatchObject({ i: "1", x: 0, y: 0, w: 2, h: 2 });
    expect(layouts.xxs![1]).toMatchObject({ i: "2", x: 0, y: 2, w: 2, h: 2 });
  });
});

describe("clampLayoutToCols", () => {
  it("reduces width so x + w does not exceed the column count", () => {
    const clamped = clampLayoutToCols(
      [{ i: "a", x: 10, y: 0, w: 6, h: 2 }],
      12,
    );
    expect(clamped[0]).toMatchObject({ i: "a", x: 10, y: 0, w: 2, h: 2 });
  });

  it("moves an item fully beyond the right edge to the last column", () => {
    const clamped = clampLayoutToCols(
      [{ i: "a", x: 15, y: 0, w: 3, h: 2 }],
      12,
    );
    expect(clamped[0]).toMatchObject({ i: "a", x: 11, y: 0, w: 1, h: 2 });
  });
});
