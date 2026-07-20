import { getBreakpointFromWidth, getColsFromBreakpoint } from "react-grid-layout";

const DEFAULT_COLS = 12;
const MAX_Y = 100;

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
