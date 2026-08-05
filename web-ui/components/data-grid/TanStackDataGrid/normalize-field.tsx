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


/**
 * Normalize a field name for scope matching: lower-case and strip surrounding
 * quotes. AI-generated scopes carry source_field values from
 * extract_select_columns(), whose casing/quoting can differ from the grid's
 * column labels, so match them the same case-insensitive way widget X/Y
 * detection does (commit eae03e0d).
 */
export function normalizeField(field: string): string {
  return field.trim().replace(/^"+|"+$/g, "").toLowerCase();
}