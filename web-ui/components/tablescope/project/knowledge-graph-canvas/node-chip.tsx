"use client";


import React, { useMemo } from "react";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconChartBar,
  IconChartLine,
  IconDatabase,
  IconFileText,
  IconHelpHexagon,
  IconSettings,
  IconTable,
  IconTarget,
  IconTopologyStar3,
  type Icon,
} from "@tabler/icons-react";
import type { GraphId, GraphNode } from "@/lib/ui/use-project-data";
import { cn } from "@/lib/cn";
import { alertSignFor, paletteFor } from "../knowledge-graph-style";import { AlertSign } from "./alert-sign";



export function NodeChip({
  node,
  selected,
  dimmed,
  onClick,
  style,
}: {
  node: GraphNode;
  selected: boolean;
  dimmed: boolean;
  onClick: () => void;
  style: React.CSSProperties;
}) {
  const palette = paletteFor(node.type);
  const conf = node.confidence;
  return (
    <button
      type="button"
      onClick={onClick}
      title={node.summary || node.label}
      className={cn(
        "absolute z-[5] flex items-center gap-2 rounded-lg border bg-white px-2.5 text-left shadow-sm transition-all hover:shadow-md",
        selected && "ring-2 ring-offset-1",
        dimmed && "opacity-25",
      )}
      style={{
        ...style,
        borderColor: palette.border,
        ...(selected ? { boxShadow: `0 0 0 2px ${palette.border}` } : {}),
      }}
    >
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: palette.dot }}
      />
      <span
        className="min-w-0 flex-1 truncate text-[12px] font-medium"
        style={{ color: palette.text }}
      >
        {node.label}
      </span>
      {typeof conf === "number" && conf > 0 && (
        <span className="shrink-0 rounded bg-slate-100 px-1 py-0.5 text-[10px] font-semibold text-slate-500">
          {conf.toFixed(2)}
        </span>
      )}
      <AlertSign type={node.type} />
    </button>
  );
}