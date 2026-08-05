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
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";import { _currencyFmt } from "./-currency-fmt";



export function formatTypedValue(value: unknown, type: string | undefined): string {
  if (value == null || value === "") return "";
  const text = String(value);
  if (type === "currency") {
    const n = Number(text.replace(/[^0-9.\-]/g, ""));
    return Number.isFinite(n) ? _currencyFmt.format(n) : text;
  }
  if (type === "number") {
    const n = Number(text.replace(/,/g, ""));
    if (!Number.isFinite(n)) return text;
    // Format with 2 decimal places if the number has a fractional part
    if (!Number.isInteger(n)) {
      return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return n.toLocaleString();
  }
  if (type === "date") {
    const d = new Date(text);
    return Number.isNaN(d.getTime()) ? text : d.toLocaleDateString();
  }
  // Auto-detect numeric values with decimals even without explicit type
  if (type === undefined || type === "string") {
    const n = Number(text);
    if (Number.isFinite(n) && text.includes(".") && !Number.isInteger(n)) {
      return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
  }
  return text;
}