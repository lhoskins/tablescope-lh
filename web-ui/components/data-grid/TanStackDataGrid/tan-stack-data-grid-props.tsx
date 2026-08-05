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
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";import { QueryRef } from "./query-ref";



export type TanStackDataGridProps = {
  columns: string[];
  rows: Record<string, unknown>[];
  loading?: boolean;
  height?: number;
  queryId?: number;
  queryName?: string;
  availableQueries?: QueryRef[];
  canEditScopes?: boolean;
  projectId?: number;
  columnTypes?: { field: string; name?: string; type: string }[];
};