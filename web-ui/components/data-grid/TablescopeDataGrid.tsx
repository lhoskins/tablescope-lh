"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DataGridPremium,
  GridColumnMenu,
  useGridApiRef,
  type GridColDef,
  type GridColumnMenuProps,
  type GridColumnVisibilityModel,
} from "@mui/x-data-grid-premium";
import { LicenseInfo } from "@mui/x-license";
import MenuItem from "@mui/material/MenuItem";
import { apiClient } from "@/lib/api-client";
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";

// MUI X Premium license key (optional). Without it the grid runs with a
// watermark + console warning but is otherwise fully functional.
const MUI_LICENSE_KEY = process.env.NEXT_PUBLIC_MUI_LICENSE_KEY;
if (MUI_LICENSE_KEY) {
  LicenseInfo.setLicenseKey(MUI_LICENSE_KEY);
}

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

type TablescopeDataGridProps = {
  columns: string[];
  rows: Record<string, unknown>[];
  loading?: boolean;
  height?: number;
  /** When provided, enables scope (drill-down) features for this saved query. */
  queryId?: number;
  /** Base query name shown in the breadcrumb. */
  queryName?: string;
  /** Other saved queries selectable as drill-down targets. */
  availableQueries?: QueryRef[];
  /** Whether the current user may create/edit/delete scopes. */
  canEditScopes?: boolean;
  /** Project id, used to fetch target-query columns for the scope dialog. */
  projectId?: number;
  /** Per-column formatting hints (currency/date/number) for item 6. */
  columnTypes?: { field: string; name?: string; type: string }[];
};

const ROW_ID = "__tsid";

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

export function TablescopeDataGrid({
  columns,
  rows,
  loading = false,
  height = 460,
  queryId,
  queryName = "Results",
  availableQueries = [],
  canEditScopes = false,
  projectId,
  columnTypes = [],
}: TablescopeDataGridProps) {
  // ── Drill-down breadcrumb (stack of levels) ──────────────────────
  const [levels, setLevels] = useState<Level[]>([
    { queryId: queryId ?? null, name: queryName, columns, rows },
  ]);
  const [drilling, setDrilling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset to the base level whenever the source result changes.
  useEffect(() => {
    setLevels([{ queryId: queryId ?? null, name: queryName, columns, rows }]);
    setError(null);
  }, [columns, rows, queryId, queryName]);

  const current = levels[levels.length - 1];
  const currentQueryId = current.queryId;

  // ── Scope metadata for the current query ─────────────────────────
  const [scopes, setScopes] = useState<QueryScope[]>([]);

  const loadScopes = useCallback(async (qid: number | null) => {
    if (qid == null) {
      setScopes([]);
      return;
    }
    try {
      const data = await apiClient.get<QueryScope[]>(`/api/query-scopes?query_id=${qid}`);
      setScopes(data);
    } catch {
      setScopes([]);
    }
  }, []);

  useEffect(() => {
    loadScopes(currentQueryId);
  }, [currentQueryId, loadScopes]);

  const scopesByField = useMemo(() => {
    const m: Record<string, QueryScope> = {};
    for (const s of scopes) m[s.source_field] = s;
    return m;
  }, [scopes]);

  // ── Drill-down on scoped cell click ──────────────────────────────
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
          {
            queryId: res.target_query_id,
            name: res.target_query_name,
            columns: res.columns,
            rows: res.rows,
          },
        ]);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setDrilling(false);
      }
    },
    [scopesByField],
  );

  // ── Scope create/edit dialog ─────────────────────────────────────
  const [dialogField, setDialogField] = useState<string | null>(null);
  const [editing, setEditing] = useState<QueryScope | null>(null);
  const [targetQueryId, setTargetQueryId] = useState<number | "">("");
  const [targetField, setTargetField] = useState("");
  const [saving, setSaving] = useState(false);

  // Columns of the selected target query, used to populate the target-field
  // dropdown in the scope dialog.
  const [targetFields, setTargetFields] = useState<string[]>([]);
  const [targetFieldsLoading, setTargetFieldsLoading] = useState(false);

  useEffect(() => {
    if (targetQueryId === "") {
      setTargetFields([]);
      return;
    }
    const tq = availableQueries.find((q) => q.id === targetQueryId);
    if (!tq) {
      setTargetFields([]);
      return;
    }
    let cancelled = false;
    setTargetFieldsLoading(true);
    apiClient
      .post<{ columns: string[] }>("/api/query/datasource", {
        tableName: tq.leftDatasource ?? "",
        limit: 1,
        project_id: projectId,
        sql: tq.sql ?? undefined,
      })
      .then((r) => {
        if (!cancelled) setTargetFields(r.columns ?? []);
      })
      .catch(() => {
        if (!cancelled) setTargetFields([]);
      })
      .finally(() => {
        if (!cancelled) setTargetFieldsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [targetQueryId, availableQueries, projectId]);

  const openScopeDialog = useCallback(
    (field: string) => {
      const existing = scopesByField[field];
      setDialogField(field);
      setEditing(existing ?? null);
      setTargetQueryId(existing ? existing.target_query_id : "");
      setTargetField(existing ? existing.target_field : "");
    },
    [scopesByField],
  );

  const closeDialog = () => {
    setDialogField(null);
    setEditing(null);
    setTargetQueryId("");
    setTargetField("");
  };

  const saveScope = async () => {
    if (!dialogField || currentQueryId == null || targetQueryId === "" || !targetField) return;
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await apiClient.patch<QueryScope>(`/api/query-scopes/${editing.id}`, {
          query_id: currentQueryId,
          source_field: dialogField,
          target_query_id: targetQueryId,
          target_field: targetField,
        });
      } else {
        await apiClient.post<QueryScope>("/api/query-scopes", {
          query_id: currentQueryId,
          source_field: dialogField,
          target_query_id: targetQueryId,
          target_field: targetField,
        });
      }
      await loadScopes(currentQueryId);
      closeDialog();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const removeScope = async (scope: QueryScope) => {
    setError(null);
    try {
      await apiClient.delete(`/api/query-scopes/${scope.id}`);
      await loadScopes(currentQueryId);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const deleteEditingScope = async () => {
    if (!editing) return;
    setSaving(true);
    await removeScope(editing);
    setSaving(false);
    closeDialog();
  };

  // ── Column visibility + order persistence ────────────────────────
  // When the grid is bound to a saved query we persist per-user layout to the
  // database (so it follows the user across devices); otherwise we fall back to
  // localStorage keyed by the query name.
  const apiRef = useGridApiRef();
  const storageKey = `tablescope-grid-cols-${currentQueryId ?? queryName ?? "default"}`;
  const [colVisibility, setColVisibility] = useState<GridColumnVisibilityModel>({});
  const [columnOrder, setColumnOrder] = useState<string[]>([]);

  const persistPrefs = useCallback(
    (order: string[], hidden: string[]) => {
      if (currentQueryId != null) {
        apiClient
          .put(`/api/grid-preferences/${currentQueryId}`, {
            column_order: order,
            hidden_columns: hidden,
          })
          .catch(() => {});
      } else if (typeof window !== "undefined") {
        window.localStorage.setItem(
          storageKey,
          JSON.stringify({ order, hidden }),
        );
      }
    },
    [currentQueryId, storageKey],
  );

  // Load saved preferences whenever the bound query changes.
  useEffect(() => {
    let cancelled = false;
    const apply = (order: string[], hidden: string[]) => {
      if (cancelled) return;
      setColumnOrder(order ?? []);
      const model: GridColumnVisibilityModel = {};
      for (const f of hidden ?? []) model[f] = false;
      setColVisibility(model);
    };
    if (currentQueryId != null) {
      apiClient
        .get<{ column_order: string[]; hidden_columns: string[] }>(
          `/api/grid-preferences/${currentQueryId}`,
        )
        .then((p) => apply(p.column_order, p.hidden_columns))
        .catch(() => apply([], []));
    } else if (typeof window !== "undefined") {
      try {
        const raw = window.localStorage.getItem(storageKey);
        const parsed = raw ? JSON.parse(raw) : null;
        apply(parsed?.order ?? [], parsed?.hidden ?? []);
      } catch {
        apply([], []);
      }
    } else {
      apply([], []);
    }
    return () => {
      cancelled = true;
    };
  }, [currentQueryId, storageKey]);

  const hiddenFromModel = (model: GridColumnVisibilityModel): string[] =>
    Object.entries(model)
      .filter(([, visible]) => visible === false)
      .map(([field]) => field);

  const onColVisibilityChange = (model: GridColumnVisibilityModel) => {
    setColVisibility(model);
    persistPrefs(columnOrder, hiddenFromModel(model));
  };

  const onColumnOrderChange = () => {
    if (!apiRef.current) return;
    const order = apiRef.current
      .getAllColumns()
      .map((c) => c.field)
      .filter((f) => f !== ROW_ID);
    setColumnOrder(order);
    persistPrefs(order, hiddenFromModel(colVisibility));
  };

  // ── Grid rows + columns ──────────────────────────────────────────
  const gridRows = useMemo(
    () => current.rows.map((r, i) => ({ ...r, [ROW_ID]: i })),
    [current.rows],
  );

  const scopeEnabled = canEditScopes && currentQueryId != null;

  // Apply the saved column order: ordered fields first (that still exist),
  // then any remaining columns in their natural order.
  const orderedFields = useMemo(() => {
    if (columnOrder.length === 0) return current.columns;
    const present = new Set(current.columns);
    const ordered = columnOrder.filter((f) => present.has(f));
    const remaining = current.columns.filter((f) => !ordered.includes(f));
    return [...ordered, ...remaining];
  }, [current.columns, columnOrder]);

  // Map column field -> formatting type (currency/date/number) for item 6.
  // The view normalizes spaces to underscores, so match either spelling.
  const typeByField = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of columnTypes) {
      if (c.field) map[c.field] = c.type;
      if (c.name) map[c.name] = c.type;
    }
    return map;
  }, [columnTypes]);

  const gridColumns = useMemo<GridColDef[]>(
    () =>
      orderedFields.map((field) => ({
        field,
        headerName: field,
        flex: 1,
        minWidth: 130,
        sortable: true,
        filterable: true,
        renderHeader: () => {
          const scoped = !!scopesByField[field];
          return (
            <span className="flex items-center gap-1 font-medium">
              {field}
              {scoped && (
                <span title="Drill-down enabled" className="text-blue-600">
                  &#128279;
                </span>
              )}
            </span>
          );
        },
        renderCell: (params) => {
          const scoped = !!scopesByField[field];
          const fieldType = typeByField[field];
          const text =
            params.value == null
              ? ""
              : formatTypedValue(params.value, fieldType);
          const numeric = fieldType === "currency" || fieldType === "number";
          if (!scoped) {
            return (
              <span className={numeric ? "block w-full text-right tabular-nums" : undefined}>
                {text}
              </span>
            );
          }
          return (
            <span
              className="cursor-pointer text-blue-700 underline decoration-dotted underline-offset-2"
              title="Click to drill down"
            >
              {text}
            </span>
          );
        },
      })),
    [orderedFields, scopesByField, typeByField],
  );

  // ── Custom column menu (Create / Edit Scope) ─────────────────────
  const ColumnMenu = useCallback(
    (props: GridColumnMenuProps) => {
      const field = props.colDef.field;
      const scoped = !!scopesByField[field];
      return (
        <GridColumnMenu
          {...props}
          slots={
            scopeEnabled
              ? {
                  columnMenuUserItem: () => (
                    <MenuItem
                      onClick={(e) => {
                        props.hideMenu(e);
                        openScopeDialog(field);
                      }}
                    >
                      {scoped ? "Edit Scope…" : "Create Scope…"}
                    </MenuItem>
                  ),
                }
              : undefined
          }
          slotProps={scopeEnabled ? { columnMenuUserItem: { displayOrder: 15 } } : undefined}
        />
      );
    },
    [scopeEnabled, scopesByField, openScopeDialog],
  );

  // All saved queries are valid drill-down targets (including the current one,
  // e.g. to filter the same query by a clicked value).
  const targetQueryChoices = availableQueries;

  return (
    <div>
      {/* Breadcrumb trail */}
      {levels.length > 1 && (
        <div className="mb-2 flex flex-wrap items-center gap-1 text-xs text-slate-600">
          {levels.map((lvl, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-slate-400">→</span>}
              <button
                type="button"
                onClick={() => setLevels((prev) => prev.slice(0, i + 1))}
                className={
                  i === levels.length - 1
                    ? "font-semibold text-slate-800"
                    : "text-blue-600 hover:text-blue-800"
                }
              >
                {lvl.name}
              </button>
            </span>
          ))}
        </div>
      )}

      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      {/* Scope trace — shown above the column headers */}
      {scopeEnabled && scopes.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs text-slate-700">
          <span className="font-semibold uppercase tracking-wide text-blue-700">
            Scopes:
          </span>
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
                <span>
                  {tq ? tq.name : `query #${s.target_query_id}`}.{s.target_field}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <div style={{ height, width: "100%" }}>
        <DataGridPremium
          apiRef={apiRef}
          rows={gridRows}
          columns={gridColumns}
          getRowId={(row) => row[ROW_ID] as number}
          loading={loading || drilling}
          density="compact"
          columnVisibilityModel={colVisibility}
          onColumnVisibilityModelChange={onColVisibilityChange}
          onColumnOrderChange={onColumnOrderChange}
          onCellClick={(params) => drilldown(params.field, params.value)}
          slots={{ columnMenu: ColumnMenu }}
          initialState={{ pagination: { paginationModel: { pageSize: 50, page: 0 } } }}
          pageSizeOptions={[25, 50, 100]}
          disableRowSelectionOnClick
        />
      </div>

      {/* Create / Edit Scope dialog */}
      {dialogField && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
          onClick={closeDialog}
        >
          <div
            className="w-[420px] rounded-lg bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-3 text-sm font-semibold text-slate-900">
              {editing ? "Edit Scope" : "Create Scope"}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-600">Source field</label>
                <input
                  value={dialogField}
                  disabled
                  className="mt-1 w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-sm text-slate-600"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600">Target query</label>
                <select
                  value={targetQueryId}
                  onChange={(e) =>
                    setTargetQueryId(e.target.value ? Number(e.target.value) : "")
                  }
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                >
                  <option value="">Select…</option>
                  {targetQueryChoices.map((q) => (
                    <option key={q.id} value={q.id}>
                      {q.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600">Target field</label>
                {targetQueryId === "" ? (
                  <p className="mt-1 text-xs text-slate-400">Select a target query first.</p>
                ) : targetFieldsLoading ? (
                  <p className="mt-1 text-xs text-slate-400">Loading fields…</p>
                ) : targetFields.length > 0 ? (
                  <select
                    value={targetField}
                    onChange={(e) => setTargetField(e.target.value)}
                    className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  >
                    <option value="">Select…</option>
                    {targetFields.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={targetField}
                    onChange={(e) => setTargetField(e.target.value)}
                    placeholder="column in the target query result"
                    className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  />
                )}
                <p className="mt-1 text-[10px] text-slate-400">
                  The clicked value filters this field in the target query.
                </p>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-2">
              {editing && (
                <button
                  type="button"
                  onClick={deleteEditingScope}
                  disabled={saving}
                  title="Delete scope"
                  aria-label="Delete scope"
                  className="rounded-md p-1.5 text-red-500 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
                    <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                  </svg>
                </button>
              )}
              <div className="flex-1" />
              <button
                onClick={closeDialog}
                className="rounded-md bg-slate-100 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-200"
              >
                Cancel
              </button>
              <button
                onClick={saveScope}
                disabled={saving || targetQueryId === "" || !targetField}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save Scope"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
