"use client";


import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
  type VisibilityState,
  type ColumnOrderState,
  type ColumnSizingState,
} from "@tanstack/react-table";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { apiClient } from "@/lib/api-client";
import {
  SCOPES_CHANGED_EVENT,
  useNotifyScopesChanged,
} from "@/lib/ui/scope-refresh";
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";


/* ── Sortable header cell ──────────────────────────────────────────── */

export function SortableHeader({
  id,
  children,
  isResizing,
}: {
  id: string;
  children: React.ReactNode;
  isResizing: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    cursor: isResizing ? "col-resize" : "grab",
    position: "relative" as const,
  };
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </div>
  );
}