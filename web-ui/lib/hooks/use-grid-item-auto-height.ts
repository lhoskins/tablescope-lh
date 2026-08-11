"use client";

import { useEffect, useRef, useState } from "react";
import { GRID_MARGIN, GRID_ROW_HEIGHT } from "@/lib/ui/grid-layout";

function pxToGridRows(contentHeight: number): number {
  const verticalGap = GRID_MARGIN[1];
  return Math.max(
    1,
    Math.ceil((contentHeight + verticalGap) / (GRID_ROW_HEIGHT + verticalGap)),
  );
}

export function useGridItemAutoHeight(
  pinId: string | number,
  onHeightChange?: (pinId: string | number, rows: number) => void,
  disabled?: boolean,
) {
  const ref = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState<number | undefined>();
  const onHeightChangeRef = useRef(onHeightChange);
  onHeightChangeRef.current = onHeightChange;

  useEffect(() => {
    if (disabled) return;
    const el = ref.current;
    if (!el) return;

    let resizeObserver: ResizeObserver | null = null;
    let rafId: number | null = null;
    let lastRows: number | undefined;

    const update = () => {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        const height = el.getBoundingClientRect().height;
        const nextRows = pxToGridRows(height);
        if (nextRows !== lastRows) {
          lastRows = nextRows;
          setRows(nextRows);
          onHeightChangeRef.current?.(pinId, nextRows);
        }
      });
    };

    update();

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(update);
      resizeObserver.observe(el);
    } else {
      window.addEventListener("resize", update);
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else {
        window.removeEventListener("resize", update);
      }
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
      }
    };
  }, [pinId, disabled]);

  return { ref, rows };
}
