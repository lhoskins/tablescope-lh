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
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";

type QueryRef = {
  id: number;
  name: string;
  sql?: string | null;
  leftDatasource?: string | null;
};

type Level = {
  queryId: number | null;
  name: string;
  columns: string[];
  rows: Record<string, unknown>[];
};

type TanStackDataGridProps = {
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

const _currencyFmt = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
});

function formatTypedValue(value: unknown, type: string | undefined): string {
  if (value == null || value === "") return "";
  const text = String(value);
  if (type === "currency") {
    const n = Number(text.replace(/[^0-9.\-]/g, ""));
    return Number.isFinite(n) ? _currencyFmt.format(n) : text;
  }
  if (type === "number") {
    const n = Number(text.replace(/,/g, ""));
    return Number.isFinite(n) ? n.toLocaleString() : text;
  }
  if (type === "date") {
    const d = new Date(text);
    return Number.isNaN(d.getTime()) ? text : d.toLocaleDateString();
  }
  return text;
}

/* ── Sortable header cell ──────────────────────────────────────────── */

function SortableHeader({
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

/* ── Main component ──────────────────────────────────────────────── */

export function TanStackDataGrid({
  columns: inputColumns,
  rows: inputRows,
  loading = false,
  height = 460,
  queryId,
  queryName = "Results",
  availableQueries = [],
  canEditScopes = false,
  projectId,
  columnTypes = [],
}: TanStackDataGridProps) {
  // ── Drill-down breadcrumb ───────────────────────────────────────
  const [levels, setLevels] = useState<Level[]>([
    { queryId: queryId ?? null, name: queryName, columns: inputColumns, rows: inputRows },
  ]);
  const [drilling, setDrilling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLevels([{ queryId: queryId ?? null, name: queryName, columns: inputColumns, rows: inputRows }]);
    setError(null);
  }, [inputColumns, inputRows, queryId, queryName]);

  const current = levels[levels.length - 1];
  const currentQueryId = current.queryId;

  // ── Scopes ──────────────────────────────────────────────────────
  const [scopes, setScopes] = useState<QueryScope[]>([]);

  const loadScopes = useCallback(async (qid: number | null) => {
    if (qid == null) { setScopes([]); return; }
    try {
      const data = await apiClient.get<QueryScope[]>(`/api/query-scopes?query_id=${qid}`);
      setScopes(data);
    } catch { setScopes([]); }
  }, []);

  useEffect(() => { loadScopes(currentQueryId); }, [currentQueryId, loadScopes]);

  const scopesByField = useMemo(() => {
    const m: Record<string, QueryScope> = {};
    for (const s of scopes) m[s.source_field] = s;
    return m;
  }, [scopes]);

  // ── Drill-down on scoped cell click ─────────────────────────────
  const drilldown = useCallback(
    async (field: string, value: unknown) => {
      const scope = scopesByField[field];
      if (!scope) return;
      setDrilling(true);
      setError(null);
      try {
        const res = await apiClient.post<QueryScopeFilterResponse>(
          "/api/query-scopes/filter",
          { scope_id: scope.id, value, limit: 1000 },
        );
        setLevels((prev) => [
          ...prev,
          { queryId: res.target_query_id, name: res.target_query_name, columns: res.columns, rows: res.rows },
        ]);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setDrilling(false);
      }
    },
    [scopesByField],
  );

  // ── Scope dialog state ─────────────────────────────────────────
  const [dialogField, setDialogField] = useState<string | null>(null);
  const [editing, setEditing] = useState<QueryScope | null>(null);
  const [targetQueryId, setTargetQueryId] = useState<number | "">("");
  const [targetField, setTargetField] = useState("");
  const [saving, setSaving] = useState(false);
  const [targetFields, setTargetFields] = useState<string[]>([]);
  const [targetFieldsLoading, setTargetFieldsLoading] = useState(false);

  useEffect(() => {
    if (targetQueryId === "") { setTargetFields([]); return; }
    const tq = availableQueries.find((q) => q.id === targetQueryId);
    if (!tq) { setTargetFields([]); return; }
    let cancelled = false;
    setTargetFieldsLoading(true);
    apiClient
      .post<{ columns: string[] }>("/api/query/datasource", {
        tableName: tq.leftDatasource ?? "",
        limit: 1,
        project_id: projectId,
        sql: tq.sql ?? undefined,
      })
      .then((r) => { if (!cancelled) setTargetFields(r.columns ?? []); })
      .catch(() => { if (!cancelled) setTargetFields([]); })
      .finally(() => { if (!cancelled) setTargetFieldsLoading(false); });
    return () => { cancelled = true; };
  }, [targetQueryId, availableQueries, projectId]);

  const openScopeDialog = useCallback((field: string) => {
    const existing = scopesByField[field];
    setDialogField(field);
    setEditing(existing ?? null);
    setTargetQueryId(existing ? existing.target_query_id : "");
    setTargetField(existing ? existing.target_field : "");
  }, [scopesByField]);

  const closeDialog = () => { setDialogField(null); setEditing(null); setTargetQueryId(""); setTargetField(""); };

  const saveScope = async () => {
    if (!dialogField || currentQueryId == null || targetQueryId === "" || !targetField) return;
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await apiClient.patch<QueryScope>(`/api/query-scopes/${editing.id}`, {
          query_id: currentQueryId, source_field: dialogField, target_query_id: targetQueryId, target_field: targetField,
        });
      } else {
        await apiClient.post<QueryScope>("/api/query-scopes", {
          query_id: currentQueryId, source_field: dialogField, target_query_id: targetQueryId, target_field: targetField,
        });
      }
      await loadScopes(currentQueryId);
      closeDialog();
    } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  };

  const removeScope = async (scope: QueryScope) => {
    setError(null);
    try { await apiClient.delete(`/api/query-scopes/${scope.id}`); await loadScopes(currentQueryId); }
    catch (e) { setError((e as Error).message); }
  };

  const deleteEditingScope = async () => {
    if (!editing) return;
    setSaving(true);
    await removeScope(editing);
    setSaving(false);
    closeDialog();
  };

  // ── Column layout persistence ──────────────────────────────────
  const storageKey = `tablescope-grid-cols-${currentQueryId ?? queryName ?? "default"}`;

  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>([]);
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [pageSize, setPageSize] = useState(50);

  const persistPrefs = useCallback(
    (order: string[], hidden: string[]) => {
      if (currentQueryId != null) {
        apiClient
          .put(`/api/grid-preferences/${currentQueryId}`, { column_order: order, hidden_columns: hidden })
          .catch(() => {});
      } else if (typeof window !== "undefined") {
        window.localStorage.setItem(storageKey, JSON.stringify({ order, hidden }));
      }
    },
    [currentQueryId, storageKey],
  );

  useEffect(() => {
    let cancelled = false;
    const apply = (order: string[], hidden: string[]) => {
      if (cancelled) return;
      setColumnOrder(order);
      const vis: VisibilityState = {};
      for (const f of hidden) vis[f] = false;
      setColumnVisibility(vis);
    };
    if (currentQueryId != null) {
      apiClient
        .get<{ column_order: string[]; hidden_columns: string[] }>(`/api/grid-preferences/${currentQueryId}`)
        .then((p) => apply(p.column_order, p.hidden_columns))
        .catch(() => apply([], []));
    } else if (typeof window !== "undefined") {
      try {
        const raw = window.localStorage.getItem(storageKey);
        const parsed = raw ? JSON.parse(raw) : null;
        apply(parsed?.order ?? [], parsed?.hidden ?? []);
      } catch { apply([], []); }
    } else { apply([], []); }
    return () => { cancelled = true; };
  }, [currentQueryId, storageKey]);

  const hiddenFromVis = (vis: VisibilityState): string[] =>
    Object.entries(vis).filter(([, v]) => v === false).map(([f]) => f);

  // ── Column type map ─────────────────────────────────────────────
  const typeByField = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of columnTypes) {
      if (c.field) map[c.field] = c.type;
      if (c.name) map[c.name] = c.type;
    }
    return map;
  }, [columnTypes]);

  // ── TanStack column defs ────────────────────────────────────────
  const scopeEnabled = canEditScopes && currentQueryId != null;

  const tableColumns = useMemo<ColumnDef<Record<string, unknown>>[]>(
    () =>
      current.columns.map((field) => ({
        id: field,
        accessorKey: field,
        header: () => {
          const scoped = !!scopesByField[field];
          return (
            <span className="flex items-center gap-1 font-medium text-xs">
              {field}
              {scoped && <span title="Drill-down enabled" className="text-blue-600">&#128279;</span>}
            </span>
          );
        },
        cell: (info) => {
          const val = info.getValue();
          const scoped = !!scopesByField[field];
          const fieldType = typeByField[field];
          const text = val == null ? "" : formatTypedValue(val, fieldType);
          const numeric = fieldType === "currency" || fieldType === "number";
          if (!scoped) {
            return <span className={numeric ? "block w-full text-right tabular-nums" : undefined}>{text}</span>;
          }
          return (
            <span
              className="cursor-pointer"
              title="Click to drill down"
              onClick={() => drilldown(field, val)}
            >
              {text}
            </span>
          );
        },
        size: 150,
        minSize: 80,
        enableSorting: true,
        enableColumnFilter: true,
      })),
    [current.columns, scopesByField, typeByField, drilldown],
  );

  // ── Row data with stable id ─────────────────────────────────────
  const tableData = useMemo(
    () => current.rows.map((r, i) => ({ ...r, __rowIdx: i })),
    [current.rows],
  );

  // ── Table instance ──────────────────────────────────────────────
  const table = useReactTable({
    data: tableData,
    columns: tableColumns,
    state: { sorting, columnFilters, globalFilter, columnVisibility, columnOrder, columnSizing, pagination: { pageIndex: 0, pageSize } },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: (updater) => {
      setColumnVisibility((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        persistPrefs(columnOrder, hiddenFromVis(next));
        return next;
      });
    },
    onColumnOrderChange: (updater) => {
      setColumnOrder((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        persistPrefs(next, hiddenFromVis(columnVisibility));
        return next;
      });
    },
    onColumnSizingChange: setColumnSizing,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    columnResizeMode: "onChange",
    enableColumnResizing: true,
  });

  // ── dnd-kit drag-and-drop for column reorder ────────────────────
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );

  const headerIds = table.getHeaderGroups()[0]?.headers.map((h) => h.id) ?? [];

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = headerIds.indexOf(String(active.id));
    const newIndex = headerIds.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    const newOrder = arrayMove(headerIds, oldIndex, newIndex);
    setColumnOrder(newOrder);
    persistPrefs(newOrder, hiddenFromVis(columnVisibility));
  };

  // ── Column visibility menu ──────────────────────────────────────
  const [showColMenu, setShowColMenu] = useState(false);
  const colMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showColMenu) return;
    const handler = (e: MouseEvent) => {
      if (colMenuRef.current && !colMenuRef.current.contains(e.target as Node)) setShowColMenu(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showColMenu]);

  // ── Context menu for column (scope create/edit) ─────────────────
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; field: string } | null>(null);
  const ctxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!contextMenu) return;
    const handler = (e: MouseEvent) => {
      if (ctxRef.current && !ctxRef.current.contains(e.target as Node)) setContextMenu(null);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [contextMenu]);

  // ── Pagination ──────────────────────────────────────────────────
  const pageCount = table.getPageCount();
  const pageIndex = table.getState().pagination.pageIndex;

  const targetQueryChoices = availableQueries;

  return (
    <div>
      {/* Breadcrumb trail */}
      {levels.length > 1 && (
        <div className="mb-2 flex flex-wrap items-center gap-1 text-xs text-slate-600">
          {levels.map((lvl, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-slate-400">&rarr;</span>}
              <button
                type="button"
                onClick={() => setLevels((prev) => prev.slice(0, i + 1))}
                className={i === levels.length - 1 ? "font-semibold text-slate-800" : "text-blue-600 hover:text-blue-800"}
              >
                {lvl.name}
              </button>
            </span>
          ))}
        </div>
      )}

      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      {/* Scope trace */}
      {scopeEnabled && scopes.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs text-slate-700">
          <span className="font-semibold uppercase tracking-wide text-blue-700">Scopes:</span>
          {scopes.map((s) => {
            const tq = availableQueries.find((q) => q.id === s.target_query_id);
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => openScopeDialog(s.source_field)}
                title="Edit scope"
                className="flex items-center gap-1 rounded-full border border-blue-200 bg-white px-2 py-0.5 hover:border-blue-400 hover:bg-blue-100"
              >
                <span className="text-blue-600">&#128279;</span>
                <span className="font-medium">{s.source_field}</span>
                <span className="text-slate-400">&rarr;</span>
                <span>{tq ? tq.name : `query #${s.target_query_id}`}.{s.target_field}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Toolbar */}
      <div className="mb-2 flex items-center gap-2">
        <input
          type="text"
          placeholder="Search all columns..."
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs w-48"
        />
        <div className="relative" ref={colMenuRef}>
          <button
            onClick={() => setShowColMenu((v) => !v)}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Columns
          </button>
          {showColMenu && (
            <div className="absolute left-0 top-full z-30 mt-1 w-56 max-h-64 overflow-auto rounded-md border border-slate-200 bg-white py-1 shadow-lg">
              {table.getAllLeafColumns().map((col) => (
                <label key={col.id} className="flex items-center gap-2 px-3 py-1 text-xs hover:bg-slate-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={col.getIsVisible()}
                    onChange={col.getToggleVisibilityHandler()}
                    className="h-3 w-3 rounded border-slate-300"
                  />
                  {col.id}
                </label>
              ))}
            </div>
          )}
        </div>
        <span className="ml-auto text-xs text-slate-400">
          {table.getFilteredRowModel().rows.length} row{table.getFilteredRowModel().rows.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      <div style={{ height: height - 50, width: "100%" }} className="overflow-auto rounded-md border border-slate-200">
        {(loading || drilling) && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60">
            <span className="text-sm text-slate-400">Loading...</span>
          </div>
        )}
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <table className="w-full border-collapse text-xs" style={{ minWidth: table.getTotalSize() }}>
            <thead className="sticky top-0 z-10 bg-slate-50">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  <SortableContext items={headerGroup.headers.map((h) => h.id)} strategy={horizontalListSortingStrategy}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        style={{ width: header.getSize(), position: "relative" }}
                        className="border-b border-slate-200 px-2 py-1.5 text-left font-semibold text-slate-700 select-none"
                        onContextMenu={(e) => {
                          if (scopeEnabled) {
                            e.preventDefault();
                            setContextMenu({ x: e.clientX, y: e.clientY, field: header.id });
                          }
                        }}
                      >
                        <SortableHeader id={header.id} isResizing={header.column.getIsResizing()}>
                          <div
                            className="flex items-center gap-1 cursor-pointer"
                            onClick={header.column.getToggleSortingHandler()}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {header.column.getIsSorted() === "asc" && <span className="text-blue-500">↑</span>}
                            {header.column.getIsSorted() === "desc" && <span className="text-blue-500">↓</span>}
                          </div>
                        </SortableHeader>
                        {/* Resize handle */}
                        <div
                          onMouseDown={header.getResizeHandler()}
                          onTouchStart={header.getResizeHandler()}
                          className={`absolute right-0 top-0 h-full w-1 cursor-col-resize select-none touch-none ${
                            header.column.getIsResizing() ? "bg-blue-500" : "hover:bg-slate-300"
                          }`}
                        />
                      </th>
                    ))}
                  </SortableContext>
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 hover:bg-blue-50/30">
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={{ width: cell.column.getSize() }}
                      className="px-2 py-1 text-slate-600 truncate"
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
              {table.getRowModel().rows.length === 0 && (
                <tr>
                  <td colSpan={current.columns.length} className="px-4 py-8 text-center text-sm text-slate-400">
                    No data
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </DndContext>
      </div>

      {/* Pagination */}
      <div className="mt-2 flex items-center justify-between text-xs text-slate-600">
        <div className="flex items-center gap-2">
          <span>Rows per page:</span>
          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); table.setPageSize(Number(e.target.value)); }}
            className="rounded border border-slate-300 px-1 py-0.5 text-xs"
          >
            {[25, 50, 100].map((s) => (<option key={s} value={s}>{s}</option>))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-40"
          >
            Prev
          </button>
          <span>Page {pageIndex + 1} of {pageCount}</span>
          <button
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>

      {/* Column context menu (Create/Edit scope) */}
      {contextMenu && (
        <div
          ref={ctxRef}
          style={{ position: "fixed", left: contextMenu.x, top: contextMenu.y }}
          className="z-50 rounded-md border border-slate-200 bg-white py-1 shadow-lg"
        >
          <button
            className="w-full px-4 py-1.5 text-left text-xs hover:bg-slate-50"
            onClick={() => { openScopeDialog(contextMenu.field); setContextMenu(null); }}
          >
            {scopesByField[contextMenu.field] ? "Edit Scope…" : "Create Scope…"}
          </button>
        </div>
      )}

      {/* Scope dialog */}
      {dialogField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={closeDialog}>
          <div className="w-[420px] rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-3 text-sm font-semibold text-slate-900">
              {editing ? "Edit Scope" : "Create Scope"}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-600">Source field</label>
                <input value={dialogField} disabled className="mt-1 w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-sm text-slate-600" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600">Target query</label>
                <select value={targetQueryId} onChange={(e) => setTargetQueryId(e.target.value ? Number(e.target.value) : "")} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="">Select…</option>
                  {targetQueryChoices.map((q) => (<option key={q.id} value={q.id}>{q.name}</option>))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600">Target field</label>
                {targetQueryId === "" ? (
                  <p className="mt-1 text-xs text-slate-400">Select a target query first.</p>
                ) : targetFieldsLoading ? (
                  <p className="mt-1 text-xs text-slate-400">Loading fields…</p>
                ) : targetFields.length > 0 ? (
                  <select value={targetField} onChange={(e) => setTargetField(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                    <option value="">Select…</option>
                    {targetFields.map((f) => (<option key={f} value={f}>{f}</option>))}
                  </select>
                ) : (
                  <input value={targetField} onChange={(e) => setTargetField(e.target.value)} placeholder="column in the target query result" className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
                )}
                <p className="mt-1 text-[10px] text-slate-400">The clicked value filters this field in the target query.</p>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-2">
              {editing && (
                <button type="button" onClick={deleteEditingScope} disabled={saving} title="Delete scope" className="rounded-md p-1.5 text-red-500 hover:bg-red-50 hover:text-red-700 disabled:opacity-50">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
                    <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                  </svg>
                </button>
              )}
              <div className="flex-1" />
              <button onClick={closeDialog} className="rounded-md bg-slate-100 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-200">Cancel</button>
              <button onClick={saveScope} disabled={saving || targetQueryId === "" || !targetField} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Saving…" : "Save Scope"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
