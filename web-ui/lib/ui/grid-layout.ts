import {
  getBreakpointFromWidth,
  getColsFromBreakpoint,
  type LayoutItem,
  type ResizeHandleAxis,
  type ResponsiveLayouts,
} from "react-grid-layout";

const DEFAULT_COLS = 12;
const MAX_Y = 100;

/** Shared responsive breakpoints and column counts for Dashboard and Home. */
export const GRID_BREAKPOINTS: Record<string, number> = {
  lg: 1200,
  md: 996,
  sm: 768,
  xs: 480,
  xxs: 0,
};

export const GRID_COLS: Record<string, number> = {
  lg: 12,
  md: 10,
  sm: 6,
  xs: 4,
  xxs: 2,
};

export const GRID_ROW_HEIGHT = 80;
export const GRID_MARGIN: [number, number] = [10, 10];
export const GRID_CONTAINER_PADDING: [number, number] = [0, 0];
export const GRID_DRAG_HANDLE = ".widget-drag-handle";
export const GRID_RESIZE_HANDLES: ResizeHandleAxis[] = [
  "se",
  "e",
  "w",
  "s",
  "n",
  "sw",
  "nw",
  "ne",
];

export const GRID_DRAG_CONFIG = {
  enabled: true,
  handle: GRID_DRAG_HANDLE,
  bounded: false,
  threshold: 3,
} as const;

export const GRID_RESIZE_CONFIG = {
  enabled: true,
  handles: GRID_RESIZE_HANDLES,
} as const;

export interface GridItemShape {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface GridPlacementInput {
  id: string | number;
  w?: number;
  h?: number;
  x?: number;
  y?: number;
}

export function getColsForWidth(
  width: number,
  breakpoints: Record<string, number>,
  cols: Record<string, number>,
): number {
  try {
    const bp = getBreakpointFromWidth(breakpoints, width);
    return getColsFromBreakpoint(bp, cols);
  } catch {
    return DEFAULT_COLS;
  }
}

function boxesCollide(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  return (
    a.x < b.x + b.w &&
    a.x + a.w > b.x &&
    a.y < b.y + b.h &&
    a.y + a.h > b.y
  );
}

function findFirstFit(
  placed: GridItemShape[],
  w: number,
  h: number,
  cols: number,
): { x: number; y: number } {
  for (let y = 0; y < MAX_Y; y++) {
    for (let x = 0; x <= cols - w; x++) {
      const candidate = { x, y, w, h };
      if (!placed.some((p) => boxesCollide(candidate, p))) {
        return { x, y };
      }
    }
  }
  return { x: 0, y: MAX_Y };
}

/**
 * Place items on a grid without overlaps. Saved x/y are respected when they fit
 * and do not collide with items already placed; otherwise items are packed into
 * the next available position using a top-left first-fit scan.
 */
export function packGridItems(
  items: GridPlacementInput[],
  cols: number,
  defaultW = 6,
  defaultH = 4,
): GridItemShape[] {
  const placed: GridItemShape[] = [];

  for (const item of items) {
    let w = Math.max(1, item.w ?? defaultW);
    let h = Math.max(1, item.h ?? defaultH);
    w = Math.min(cols, w);

    const x = typeof item.x === "number" ? item.x : 0;
    const y = typeof item.y === "number" ? item.y : 0;

    const saved = { x, y, w, h };
    const fitsBounds = x >= 0 && y >= 0 && x + w <= cols;
    const noCollision = fitsBounds && !placed.some((p) => boxesCollide(saved, p));

    if (fitsBounds && noCollision) {
      placed.push({ i: String(item.id), x, y, w, h });
    } else {
      const pos = findFirstFit(placed, w, h, cols);
      placed.push({ i: String(item.id), x: pos.x, y: pos.y, w, h });
    }
  }

  return placed;
}

export interface GridPinShape {
  id: number | string;
  pin_type: string;
  layout?: {
    x?: number;
    y?: number;
    w?: number;
    h?: number;
    position?: number;
  } | null;
  config?: Record<string, unknown> | null;
}

export interface PinGridSize {
  w: number;
  h: number;
  minW: number;
  minH: number;
  maxW: number;
}

function widgetTypeFromConfig(config?: Record<string, unknown> | null): string | undefined {
  const widget = config?.widget as Record<string, unknown> | undefined;
  return typeof widget?.type === "string" ? widget.type : undefined;
}

export function getPinDefaultSize(
  pin: GridPinShape,
  desktopCols = DEFAULT_COLS,
): PinGridSize {
  const widgetType = widgetTypeFromConfig(pin.config);

  if (pin.pin_type === "live_widget" && widgetType === "kpi") {
    return { w: 3, h: 2, minW: 2, minH: 2, maxW: desktopCols };
  }
  if (pin.pin_type === "live_widget" && (widgetType === "table" || widgetType === "funnel")) {
    return { w: 6, h: 6, minW: 3, minH: 4, maxW: desktopCols };
  }
  return { w: 6, h: 4, minW: 2, minH: 2, maxW: desktopCols };
}

/** Build a responsive layout set for Home pins. The desktop (lg) layout is the
 *  source of truth; smaller breakpoints are derived by clamping and repacking
 *  when saved desktop dimensions no longer fit. */
export function buildResponsiveHomeLayouts(
  pins: GridPinShape[],
  breakpoints: Record<string, number> = GRID_BREAKPOINTS,
  cols: Record<string, number> = GRID_COLS,
): ResponsiveLayouts {
  const result: ResponsiveLayouts = {};

  for (const bp of Object.keys(breakpoints)) {
    const bpCols = cols[bp] ?? DEFAULT_COLS;
    const placement: GridPlacementInput[] = pins.map((pin) => {
      const defaults = getPinDefaultSize(pin, cols.lg ?? DEFAULT_COLS);
      const saved = pin.layout ?? {};
      return {
        id: pin.id,
        x: saved.x,
        y: saved.y,
        w: saved.w ?? defaults.w,
        h: saved.h ?? defaults.h,
      };
    });

    const packed = packGridItems(placement, bpCols, 6, 4);
    result[bp] = packed.map((item) => {
      const pin = pins.find((p) => String(p.id) === item.i);
      const defaults = getPinDefaultSize(pin ?? { id: item.i, pin_type: "insight_card" }, cols.lg ?? DEFAULT_COLS);
      return {
        i: item.i,
        x: item.x,
        y: item.y,
        w: item.w,
        h: item.h,
        minW: defaults.minW,
        minH: defaults.minH,
        maxW: Math.min(defaults.maxW, bpCols),
      } as LayoutItem;
    });
  }

  return result;
}

/** Clamp a layout to a specific column count, reducing widths and positions
 *  so no item extends past the right edge. This is a pure geometry clamp; it
 *  does not repack for overlap. Use `packGridItems` when overlap must be removed. */
export function clampLayoutToCols(layout: LayoutItem[], cols: number): LayoutItem[] {
  return layout.map((item) => {
    const x = Math.min(item.x, cols - 1);
    const w = Math.min(item.w, cols - x);
    return { ...item, x, w: Math.max(1, w) };
  });
}
