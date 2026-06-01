"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DataGrid,
  GridColumnMenu,
  type GridColDef,
  type GridColumnMenuProps,
  type GridColumnVisibilityModel,
} from "@mui/x-data-grid";
import MenuItem from "@mui/material/MenuItem";
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
};

const ROW_ID = "__tsid";

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

  // ── Column visibility persistence (localStorage per query) ───────
  const storageKey = `tablescope-grid-cols-${currentQueryId ?? "default"}`;
  const [colVisibility, setColVisibility] = useState<GridColumnVisibilityModel>({});

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(storageKey);
      setColVisibility(raw ? (JSON.parse(raw) as GridColumnVisibilityModel) : {});
    } catch {
      setColVisibility({});
    }
  }, [storageKey]);

  const onColVisibilityChange = (model: GridColumnVisibilityModel) => {
    setColVisibility(model);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(storageKey, JSON.stringify(model));
    }
  };

  // ── Grid rows + columns ──────────────────────────────────────────
  const gridRows = useMemo(
    () => current.rows.map((r, i) => ({ ...r, [ROW_ID]: i })),
    [current.rows],
  );

  const scopeEnabled = canEditScopes && currentQueryId != null;

  const gridColumns = useMemo<GridColDef[]>(
    () =>
      current.columns.map((field) => ({
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
          const text = params.value == null ? "" : String(params.value);
          if (!scoped) return <span>{text}</span>;
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
    [current.columns, scopesByField],
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

      <div style={{ height, width: "100%" }}>
        <DataGrid
          rows={gridRows}
          columns={gridColumns}
          getRowId={(row) => row[ROW_ID] as number}
          loading={loading || drilling}
          density="compact"
          columnVisibilityModel={colVisibility}
          onColumnVisibilityModelChange={onColVisibilityChange}
          onCellClick={(params) => drilldown(params.field, params.value)}
          slots={{ columnMenu: ColumnMenu }}
          initialState={{ pagination: { paginationModel: { pageSize: 50, page: 0 } } }}
          pageSizeOptions={[25, 50, 100]}
          disableRowSelectionOnClick
        />
      </div>

      {/* Scope Details panel */}
      {scopeEnabled && scopes.length > 0 && (
        <div className="mt-3 rounded-md border border-slate-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Drill-down scopes
          </p>
          <ul className="space-y-1">
            {scopes.map((s) => {
              const tq = availableQueries.find((q) => q.id === s.target_query_id);
              return (
                <li key={s.id} className="flex items-center justify-between text-xs text-slate-700">
                  <span>
                    <span className="font-medium">{s.source_field}</span> →{" "}
                    {tq ? tq.name : `query #${s.target_query_id}`}.{s.target_field}
                  </span>
                  <span className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => openScopeDialog(s.source_field)}
                      className="text-blue-600 hover:text-blue-800"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => removeScope(s)}
                      className="text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

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
            <div className="mt-4 flex justify-end gap-2">
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
