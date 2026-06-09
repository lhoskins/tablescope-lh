"use client";

import { useState, useCallback, useMemo, useEffect, DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";
import { DashboardTab } from "@/components/dashboard/DashboardTab";
import { AIPanel } from "@/components/ai/AIPanel";
import { AIPromptBar } from "@/components/ai/AIPromptBar";
import { ScopesTab } from "@/components/scopes/ScopesTab";

// Small badge describing where a datasource comes from (file type or DB engine).
function SourceBadge({ ds }: { ds: Datasource }) {
  let label: string;
  let cls: string;
  if (ds.sourceType === "saas_object") {
    const c = (ds.connectorType ?? "saas").toLowerCase();
    label =
      c === "hubspot"
        ? "HubSpot"
        : c === "salesforce"
        ? "Salesforce"
        : c === "quickbooks"
        ? "QuickBooks"
        : "SaaS";
    cls =
      c === "hubspot"
        ? "bg-orange-100 text-orange-700"
        : c === "quickbooks"
        ? "bg-green-100 text-green-700"
        : "bg-sky-100 text-sky-700";
  } else if (ds.sourceType === "database_table") {
    const db = (ds.dbType ?? "database").toLowerCase();
    label =
      db === "postgresql"
        ? "PostgreSQL"
        : db === "mysql"
        ? "MySQL"
        : db === "sqlserver"
        ? "SQL Server"
        : db === "oracle"
        ? "Oracle"
        : "Database";
    cls = "bg-indigo-100 text-indigo-700";
  } else {
    label = (ds.sourceType ?? "file").toUpperCase();
    cls = "bg-emerald-100 text-emerald-700";
  }
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{label}</span>
  );
}

// ── Types ───────────────────────────────────────────────────────────

type Project = {
  id: number;
  name: string;
  description: string | null;
  is_shared: boolean;
  scoping_enabled: boolean;
  owner_id: number | null;
};

type ColumnType = { name: string; field: string; type: string };

type Datasource = {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
  id?: number | null;
  ownerId?: number | null;
  fileMetaId?: number | null;
  projectId?: number | null;
  archived?: boolean;
  columnTypes?: ColumnType[];
};

type SavedQuery = {
  id: number;
  project_id: number;
  owner_id: number | null;
  name: string;
  description: string | null;
  left_datasource: string | null;
  right_datasource: string | null;
  join_type: string | null;
  left_column: string | null;
  right_column: string | null;
  sql_text: string | null;
};

type Member = {
  project_id: number;
  user_id: number;
  role: string;
  is_active: boolean;
  email: string;
  display_name: string | null;
};

type TenantUser = {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
};

type QueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
};

// ── Join types ──────────────────────────────────────────────────────

const JOIN_TYPES = [
  { value: "INNER JOIN", label: "Inner Join" },
  { value: "LEFT JOIN", label: "Left Join" },
  { value: "RIGHT JOIN", label: "Right Join" },
  { value: "FULL OUTER JOIN", label: "Full Outer Join" },
  { value: "CROSS JOIN", label: "Cross Join" },
];

// Parse the explicit `"ds"."col"` field list out of a SELECT statement.
// Returns [] for `SELECT *` (meaning "all fields").
function parseSelectedFields(sql: string): string[] {
  if (!sql) return [];
  const m = /select\s+([\s\S]*?)\s+from\s/i.exec(sql);
  if (!m) return [];
  const list = m[1].trim();
  if (list === "*" || list === "") return [];
  return list
    .split(",")
    .map((tok) => {
      const parts = tok
        .trim()
        .split(".")
        .map((p) => p.trim().replace(/^"|"$/g, ""));
      if (parts.length >= 2) return `${parts[0]}.${parts[1]}`;
      return parts[0] ? parts[0] : "";
    })
    .filter(Boolean);
}

function quoteField(qualified: string): string {
  const idx = qualified.indexOf(".");
  if (idx === -1) return `"${qualified}"`;
  return `"${qualified.slice(0, idx)}"."${qualified.slice(idx + 1)}"`;
}

// Normalize a `"ds"."col"` (or bare) token into the unquoted `ds.col` form.
function unquoteField(tok: string): string {
  return tok
    .trim()
    .split(".")
    .map((p) => p.trim().replace(/^"|"$/g, ""))
    .join(".");
}

type Filter = { column: string; operand: string; value: string };
type OrderByItem = { column: string; dir: string };

// Best-effort parsers so the visual controls pre-populate from saved SQL.
function parseWhere(sql: string): Filter[] {
  const m = /\swhere\s+([\s\S]*?)(?:\s+group\s+by\s|\s+order\s+by\s|\s*$)/i.exec(sql);
  if (!m) return [];
  return m[1]
    .split(/\s+and\s+/i)
    .map((clause) => {
      const inM = /^\s*("?[\w.]+"?(?:\."?[\w]+"?)?)\s+in\s*\((.*)\)\s*$/i.exec(clause);
      if (inM) {
        const vals = inM[2]
          .split(",")
          .map((v) => v.trim().replace(/^'|'$/g, ""))
          .join(", ");
        return { column: unquoteField(inM[1]), operand: "IN", value: vals };
      }
      const opM = /^\s*("?[\w.]+"?(?:\."?[\w]+"?)?)\s*(>=|<=|!=|=|>|<|like)\s*(.+?)\s*$/i.exec(
        clause,
      );
      if (!opM) return null;
      return {
        column: unquoteField(opM[1]),
        operand: opM[2].toUpperCase(),
        value: opM[3].trim().replace(/^'|'$/g, ""),
      };
    })
    .filter((f): f is Filter => f !== null && !!f.column);
}

function parseGroupBy(sql: string): string[] {
  const m = /\sgroup\s+by\s+([\s\S]*?)(?:\s+order\s+by\s|\s+having\s|\s*$)/i.exec(sql);
  if (!m) return [];
  return m[1]
    .split(",")
    .map((t) => unquoteField(t))
    .filter(Boolean);
}

function parseOrderBy(sql: string): OrderByItem[] {
  const m = /\sorder\s+by\s+([\s\S]*?)\s*$/i.exec(sql);
  if (!m) return [];
  return m[1]
    .split(",")
    .map((t) => {
      const parts = t.trim().split(/\s+/);
      const dir = /^(asc|desc)$/i.test(parts[parts.length - 1] ?? "")
        ? parts.pop()!.toUpperCase()
        : "ASC";
      return { column: unquoteField(parts.join(" ")), dir };
    })
    .filter((o) => !!o.column);
}

// Build the trailing WHERE / GROUP BY / ORDER BY clauses from visual controls.
function buildClauses(
  filters: Filter[],
  groupBy: string[],
  orderBy: OrderByItem[],
): string {
  let out = "";
  const where = filters
    .filter((f) => f.column && f.operand && f.value)
    .map((f) => {
      const col = quoteField(f.column);
      if (f.operand === "IN") {
        const vals = f.value
          .split(",")
          .map((v) => `'${v.trim()}'`)
          .join(", ");
        return `${col} IN (${vals})`;
      }
      if (f.operand === "LIKE") return `${col} LIKE '${f.value}'`;
      if (f.operand === "BEGINS WITH") return `${col} LIKE '${f.value}%'`;
      if (f.operand === "ENDS WITH") return `${col} LIKE '%${f.value}'`;
      return `${col} ${f.operand} '${f.value}'`;
    });
  if (where.length > 0) out += " WHERE " + where.join(" AND ");
  const groups = groupBy.filter(Boolean).map(quoteField);
  if (groups.length > 0) out += " GROUP BY " + groups.join(", ");
  const orders = orderBy
    .filter((o) => o.column)
    .map((o) => `${quoteField(o.column)} ${o.dir}`);
  if (orders.length > 0) out += " ORDER BY " + orders.join(", ");
  return out;
}

// ── Edit Query Form ─────────────────────────────────────────────────

function EditQueryForm({
  query,
  datasources,
  projectId,
  onSave,
  onCancel,
  isPending,
}: {
  query: SavedQuery;
  datasources: Datasource[];
  projectId: number;
  onSave: (updates: Record<string, string>) => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const [name, setName] = useState(query.name);
  const [description, setDescription] = useState(query.description ?? "");
  const [leftDs, setLeftDs] = useState(query.left_datasource ?? "");
  const [rightDs, setRightDs] = useState(query.right_datasource ?? "");
  const [jt, setJt] = useState(query.join_type ?? "INNER JOIN");
  const [lc, setLc] = useState(query.left_column ?? "");
  const [rc, setRc] = useState(query.right_column ?? "");
  const [leftCols, setLeftCols] = useState<string[]>([]);
  const [rightCols, setRightCols] = useState<string[]>([]);
  const [sqlEditing, setSqlEditing] = useState(false);
  const savedSql = query.sql_text ?? "";
  const [sqlText, setSqlText] = useState(savedSql);
  // Show join config only when a join is in play (right datasource present).
  const [showJoin, setShowJoin] = useState(!!query.right_datasource);
  // Collapsible "view fields" panel for the selected table(s).
  const [fieldsOpen, setFieldsOpen] = useState(false);
  // Once the user touches the visual params we regenerate SQL from them;
  // until then we keep showing the explicit saved SQL (with field selection).
  const [visualDirty, setVisualDirty] = useState(false);
  const markDirty = () => setVisualDirty(true);
  // Fields currently in the SELECT (fully-qualified "ds.col").  Empty = all.
  const [selectedFields, setSelectedFields] = useState<string[]>(() =>
    parseSelectedFields(savedSql),
  );
  // WHERE / GROUP BY / ORDER BY builder controls (item 4).
  const [filters, setFilters] = useState<Filter[]>(() => parseWhere(savedSql));
  const [groupBy, setGroupBy] = useState<string[]>(() => parseGroupBy(savedSql));
  const [orderBy, setOrderBy] = useState<OrderByItem[]>(() => parseOrderBy(savedSql));
  // Execute-in-editor state (parity with the Create Query flow).
  const [execResult, setExecResult] = useState<QueryResult | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);

  const allFields = useMemo(() => {
    const l = leftCols.map((c) => `${leftDs}.${c}`);
    const r = showJoin && rightDs ? rightCols.map((c) => `${rightDs}.${c}`) : [];
    return [...l, ...r];
  }, [leftCols, rightCols, leftDs, rightDs, showJoin]);

  const isAllFields = selectedFields.length === 0;
  const isFieldOn = (f: string) => isAllFields || selectedFields.includes(f);

  const toggleField = (f: string) => {
    markDirty();
    setSelectedFields((prev) => {
      const base = prev.length === 0 ? [...allFields] : prev;
      const next = base.includes(f) ? base.filter((x) => x !== f) : [...base, f];
      // Normalize "everything selected" back to [] (SELECT *).
      if (allFields.length > 0 && next.length === allFields.length) return [];
      return next;
    });
  };

  useEffect(() => {
    if (leftDs) {
      apiClient.post<{ columns: string[] }>("/api/query/datasource", { tableName: leftDs, limit: 1, project_id: projectId })
        .then((r) => setLeftCols(r.columns))
        .catch(() => setLeftCols([]));
    } else {
      setLeftCols([]);
    }
  }, [leftDs, projectId]);

  useEffect(() => {
    if (rightDs) {
      apiClient.post<{ columns: string[] }>("/api/query/datasource", { tableName: rightDs, limit: 1, project_id: projectId })
        .then((r) => setRightCols(r.columns))
        .catch(() => setRightCols([]));
    } else {
      setRightCols([]);
    }
  }, [rightDs, projectId]);

  const generatedSql = useMemo(() => {
    if (!leftDs) return "";
    const l = `"${leftDs}"`;
    // Drop any selected fields that no longer belong to an active datasource
    // (e.g. right-side fields left over after a join is removed).
    const liveFields =
      allFields.length > 0
        ? selectedFields.filter((f) => allFields.includes(f))
        : selectedFields;
    const cols = liveFields.length === 0 ? "*" : liveFields.map(quoteField).join(", ");
    const tail = buildClauses(filters, groupBy, orderBy);
    let base: string;
    if (!showJoin || !rightDs) {
      base = `SELECT ${cols} FROM ${l}`;
    } else {
      const r = `"${rightDs}"`;
      if (jt === "CROSS JOIN") {
        base = `SELECT ${cols} FROM ${l} ${jt} ${r}`;
      } else if (lc && rc) {
        base = `SELECT ${cols} FROM ${l} ${jt} ${r} ON ${l}."${lc}" = ${r}."${rc}"`;
      } else {
        return "";
      }
    }
    return base + tail;
  }, [leftDs, rightDs, jt, lc, rc, showJoin, selectedFields, allFields, filters, groupBy, orderBy]);

  // Before the user edits visual params, prefer the explicit saved SQL so the
  // editor shows the real query (with selected fields), not a regenerated
  // SELECT *.  Once they change a param, reflect the generated SQL.
  const effectiveSql = visualDirty ? generatedSql : savedSql || generatedSql;

  useEffect(() => {
    if (!sqlEditing) setSqlText(effectiveSql);
  }, [effectiveSql, sqlEditing]);

  const runQuery = useCallback(async () => {
    const sql = sqlEditing ? sqlText : effectiveSql;
    if (!sql || !leftDs) return;
    setExecuting(true);
    setExecError(null);
    setExecResult(null);
    try {
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: leftDs,
        limit: 100,
        project_id: projectId,
        sql,
      });
      setExecResult(result);
    } catch (err) {
      setExecError((err as Error).message);
    } finally {
      setExecuting(false);
    }
  }, [sqlEditing, sqlText, effectiveSql, leftDs, projectId]);

  return (
    <div className="mt-3 ml-2 rounded-lg border border-blue-200 bg-blue-50 p-4" onClick={(e) => e.stopPropagation()}>
      <h4 className="mb-3 text-sm font-semibold text-blue-900">Edit Query</h4>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Description</label>
          <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </div>
      </div>
      <div className="mb-3">
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-slate-600 mb-1">Datasource</label>
            <select value={leftDs} onChange={(e) => { markDirty(); setLeftDs(e.target.value); }}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
              <option value="">Select...</option>
              {datasources.map((d) => <option key={d.viewName} value={d.viewName}>{d.fileName}</option>)}
            </select>
          </div>
          {leftDs && !showJoin && (
            <button
              type="button"
              onClick={() => { markDirty(); setShowJoin(true); }}
              className="rounded-md border border-blue-300 bg-white px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50"
            >
              + Add Join
            </button>
          )}
        </div>
      </div>

      {/* Join config — only shown when a join is active */}
      {showJoin && (
        <div className="mb-3 rounded-md border border-blue-200 bg-white p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-blue-900">Join Configuration</span>
            <button
              type="button"
              onClick={() => {
                markDirty();
                setSqlEditing(false);
                setSelectedFields((prev) => prev.filter((f) => !rightDs || !f.startsWith(rightDs + ".")));
                setShowJoin(false);
                setRightDs("");
                setLc("");
                setRc("");
              }}
              className="text-xs text-red-500 hover:text-red-700"
            >
              Remove Join
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Join Type</label>
              <select value={jt} onChange={(e) => { markDirty(); setJt(e.target.value); }}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                {JOIN_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Right Datasource</label>
              <select value={rightDs} onChange={(e) => { markDirty(); setRightDs(e.target.value); }}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="">Select...</option>
                {datasources.map((d) => <option key={d.viewName} value={d.viewName}>{d.fileName}</option>)}
              </select>
            </div>
          </div>
          {jt !== "CROSS JOIN" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Left Column</label>
                <select value={lc} onChange={(e) => { markDirty(); setLc(e.target.value); }}
                  className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="">Select column...</option>
                  {leftCols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Right Column</label>
                <select value={rc} onChange={(e) => { markDirty(); setRc(e.target.value); }}
                  className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="">Select column...</option>
                  {rightCols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Collapsible fields panel for the selected table(s) */}
      {leftDs && (
        <div className="mb-3 rounded-md border border-slate-200 bg-white">
          <div
            onClick={() => setFieldsOpen((o) => !o)}
            className="flex cursor-pointer items-center justify-between px-3 py-2 hover:bg-slate-50"
          >
            <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
              <span className="text-slate-400">{fieldsOpen ? "▲" : "▼"}</span>
              <span>Fields ({isAllFields ? "all" : selectedFields.length} selected)</span>
            </div>
            {fieldsOpen && (
              <div className="flex gap-2">
                <button type="button" onClick={(e) => { e.stopPropagation(); markDirty(); setSelectedFields([]); }}
                  className="text-xs text-blue-600 hover:text-blue-800">Select All</button>
                <button type="button" onClick={(e) => { e.stopPropagation(); markDirty(); setSelectedFields(allFields.length ? [allFields[0]] : []); }}
                  className="text-xs text-red-500 hover:text-red-700">Clear All</button>
              </div>
            )}
          </div>
          {fieldsOpen && (
            <div className="border-t border-slate-100 px-3 py-2">
              <div className={showJoin && rightDs ? "grid grid-cols-2 gap-4" : ""}>
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{leftDs}</p>
                  <div className="flex flex-wrap gap-1">
                    {leftCols.length === 0 && <span className="text-xs text-slate-400">No fields loaded.</span>}
                    {leftCols.map((c) => {
                      const f = `${leftDs}.${c}`;
                      const on = isFieldOn(f);
                      return (
                        <button
                          key={c}
                          type="button"
                          onClick={() => toggleField(f)}
                          className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors ${
                            on
                              ? "border-blue-500 bg-blue-500 text-white"
                              : "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100"
                          }`}
                        >
                          {c}
                        </button>
                      );
                    })}
                  </div>
                </div>
                {showJoin && rightDs && (
                  <div className="border-l border-slate-100 pl-4">
                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{rightDs}</p>
                    <div className="flex flex-wrap gap-1">
                      {rightCols.length === 0 && <span className="text-xs text-slate-400">No fields loaded.</span>}
                      {rightCols.map((c) => {
                        const f = `${rightDs}.${c}`;
                        const on = isFieldOn(f);
                        return (
                          <button
                            key={c}
                            type="button"
                            onClick={() => toggleField(f)}
                            className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors ${
                              on
                                ? "border-blue-500 bg-blue-500 text-white"
                                : "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100"
                            }`}
                          >
                            {c}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
              <p className="mt-2 text-[10px] text-slate-400">
                Highlighted fields are included in the query. Click to add or remove; the SQL updates and saves with the query.
              </p>
            </div>
          )}
        </div>
      )}

      {/* + Add Filter / + Group By / + Order By — always visible as a button row */}
      {leftDs && (
        <div className="mb-3 flex gap-2">
          {filters.length === 0 && (
            <button
              type="button"
              onClick={() => { markDirty(); setFilters((p) => [...p, { column: "", operand: "=", value: "" }]); }}
              className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
            >
              + Add Filter
            </button>
          )}
          {groupBy.length === 0 && (
            <button
              type="button"
              onClick={() => { markDirty(); setGroupBy([""]); }}
              className="rounded-md border border-purple-200 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700 hover:bg-purple-100"
            >
              + Group By
            </button>
          )}
          {orderBy.length === 0 && (
            <button
              type="button"
              onClick={() => { markDirty(); setOrderBy([{ column: "", dir: "ASC" }]); }}
              className="rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100"
            >
              + Order By
            </button>
          )}
        </div>
      )}

      {/* Filters (WHERE) — expanded once a filter is added */}
      {leftDs && filters.length > 0 && (
        <div className="mb-3 rounded-md border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-700">Filters</span>
            <button
              type="button"
              onClick={() => { markDirty(); setFilters((p) => [...p, { column: "", operand: "=", value: "" }]); }}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              + Add Filter
            </button>
          </div>
          {filters.map((f, idx) => (
            <div key={idx} className="mb-2 flex items-center gap-2">
              <select
                value={f.column}
                onChange={(e) => { markDirty(); setFilters((p) => p.map((x, i) => i === idx ? { ...x, column: e.target.value } : x)); }}
                className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              >
                <option value="">Column...</option>
                {allFields.map((c) => (
                  <option key={c} value={c}>{c.split(".")[1]}{showJoin && rightDs ? ` (${c.split(".")[0]})` : ""}</option>
                ))}
              </select>
              <select
                value={f.operand}
                onChange={(e) => { markDirty(); setFilters((p) => p.map((x, i) => i === idx ? { ...x, operand: e.target.value } : x)); }}
                className="w-28 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              >
                {["=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "BEGINS WITH", "ENDS WITH"].map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
              <input
                type="text"
                value={f.value}
                onChange={(e) => { markDirty(); setFilters((p) => p.map((x, i) => i === idx ? { ...x, value: e.target.value } : x)); }}
                placeholder={f.operand === "IN" ? "val1, val2, ..." : "Value"}
                className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              />
              <button
                type="button"
                onClick={() => { markDirty(); setFilters((p) => p.filter((_, i) => i !== idx)); }}
                className="text-xs text-red-500 hover:text-red-700"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Group By — clickable field chips */}
      {leftDs && groupBy.length > 0 && (
        <div className="mb-3 rounded-md border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-700">Group By</span>
            <button type="button" onClick={() => { markDirty(); setGroupBy([]); }} className="text-xs text-red-500 hover:text-red-700">Clear</button>
          </div>
          <div className="flex flex-wrap gap-1">
            {allFields.map((f) => {
              const col = f.split(".")[1] ?? f;
              const on = groupBy.includes(f);
              return (
                <button key={f} type="button"
                  onClick={() => { markDirty(); setGroupBy((p) => on ? p.filter((x) => x !== f) : [...p, f]); }}
                  className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors ${on ? "border-purple-500 bg-purple-500 text-white" : "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100"}`}
                >{col}</button>
              );
            })}
          </div>
        </div>
      )}

      {/* Order By — clickable field chips with direction toggle */}
      {leftDs && orderBy.length > 0 && (
        <div className="mb-3 rounded-md border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-700">Order By</span>
            <button type="button" onClick={() => { markDirty(); setOrderBy([]); }} className="text-xs text-red-500 hover:text-red-700">Clear</button>
          </div>
          <div className="flex flex-wrap gap-1">
            {allFields.map((f) => {
              const col = f.split(".")[1] ?? f;
              const idx = orderBy.findIndex((o) => o.column === f);
              const on = idx >= 0;
              const dir = on ? orderBy[idx].dir : "ASC";
              return (
                <button key={f} type="button"
                  onClick={() => {
                    markDirty();
                    if (!on) { setOrderBy((p) => [...p, { column: f, dir: "ASC" }]); }
                    else if (dir === "ASC") { setOrderBy((p) => p.map((x) => x.column === f ? { ...x, dir: "DESC" } : x)); }
                    else { setOrderBy((p) => p.filter((x) => x.column !== f)); }
                  }}
                  className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors ${on ? "border-amber-500 bg-amber-500 text-white" : "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100"}`}
                >{col}{on ? (dir === "ASC" ? " ↑" : " ↓") : ""}</button>
              );
            })}
          </div>
        </div>
      )}

      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <label className="block text-xs font-medium text-slate-600">SQL</label>
          <button
            type="button"
            onClick={() => { if (sqlEditing) { setSqlText(effectiveSql); setSqlEditing(false); } else { setSqlText(effectiveSql); setSqlEditing(true); } }}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            {sqlEditing ? "Reset to generated" : "Edit SQL directly"}
          </button>
        </div>
        <textarea
          value={sqlText}
          onChange={(e) => setSqlText(e.target.value)}
          readOnly={!sqlEditing}
          rows={3}
          className={`w-full rounded-md border px-2 py-1.5 text-xs font-mono ${
            sqlEditing
              ? "border-blue-400 bg-white text-slate-900"
              : "border-slate-300 bg-slate-800 text-slate-300 cursor-default"
          }`}
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => {
            const finalSql = sqlEditing ? sqlText : effectiveSql;
            const joinActive = showJoin && !!rightDs;
            const saveRightDs =
              (sqlEditing && rightDs && !sqlText.includes(rightDs)) || !joinActive
                ? ""
                : rightDs;
            const saveJt = saveRightDs ? jt : "";
            const saveLc = saveRightDs ? lc : "";
            const saveRc = saveRightDs ? rc : "";
            onSave({
              name, description,
              left_datasource: leftDs, right_datasource: saveRightDs,
              join_type: saveJt, left_column: saveLc, right_column: saveRc,
              sql_text: finalSql,
            });
          }}
          disabled={!name.trim() || isPending}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
        >
          {isPending ? "Saving..." : "Update Query"}
        </button>
        <button
          onClick={runQuery}
          disabled={executing || !(sqlEditing ? sqlText : effectiveSql)}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {executing ? "Executing..." : "Execute"}
        </button>
        <button onClick={onCancel}
          className="rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200">
          Cancel
        </button>
      </div>

      {/* Execution results (parity with Create Query flow) */}
      {execError && <p className="mt-3 text-sm text-red-600">{execError}</p>}
      {execResult && execResult.rows.length > 0 && (
        <div className="mt-3">
          <DataGrid columns={execResult.columns} rows={execResult.rows} />
        </div>
      )}
      {execResult && execResult.rows.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">Query returned no results.</p>
      )}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────

export default function ProjectWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const projectId = Number(params.id);
  const meta = getUserMeta();

  // ── Tab state ─────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<"datasources" | "queries" | "dashboards" | "scopes" | "ai" | "members">("datasources");

  // ── Collapsible panels ──────────────────────────────────────────
  const [dsListOpen, setDsListOpen] = useState(false);
  const [queryListOpen, setQueryListOpen] = useState(false);

  // ── AI generation state ─────────────────────────────────────────
  const [aiQueryLoading, setAiQueryLoading] = useState(false);
  const [aiQueryError, setAiQueryError] = useState<string | null>(null);
  const [aiQuerySuccess, setAiQuerySuccess] = useState<string | null>(null);

  const handleAIGenerateQuery = useCallback(async (prompt: string) => {
    setAiQueryLoading(true);
    setAiQueryError(null);
    setAiQuerySuccess(null);
    try {
      const result = await apiClient.post<{ query_id: number; name: string; sql_text: string }>(
        "/api/ai/actions/generate-and-save-query",
        { project_id: projectId, prompt },
      );
      setAiQuerySuccess(`Query saved: ${result.name}`);
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
    } catch (err) {
      setAiQueryError(err instanceof Error ? err.message : "AI query generation failed");
    } finally {
      setAiQueryLoading(false);
    }
  }, [projectId, queryClient]);

  // ── Query builder state ───────────────────────────────────────────
  const [buildingQuery, setBuildingQuery] = useState(false);
  const [leftDs, setLeftDs] = useState<Datasource | null>(null);
  const [rightDs, setRightDs] = useState<Datasource | null>(null);
  const [showJoinDialog, setShowJoinDialog] = useState(false);
  // Whether the user has opted into a join (reveals the second datasource box).
  const [joinMode, setJoinMode] = useState(false);
  // Collapsible "view fields" panel for the selected table(s) in the builder.
  const [builderFieldsOpen, setBuilderFieldsOpen] = useState(false);
  const [joinType, setJoinType] = useState("INNER JOIN");
  const [leftCol, setLeftCol] = useState("");
  const [rightCol, setRightCol] = useState("");
  const [leftCols, setLeftCols] = useState<string[]>([]);
  const [rightCols, setRightCols] = useState<string[]>([]);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [filters, setFilters] = useState<{ column: string; operand: string; value: string }[]>([]);
  const [mainGroupBy, setMainGroupBy] = useState<string[]>([]);
  const [mainOrderBy, setMainOrderBy] = useState<{ column: string; dir: string }[]>([]);
  const [mainSqlEditing, setMainSqlEditing] = useState(false);
  const [customSql, setCustomSql] = useState("");

  // ── Save dialog ───────────────────────────────────────────────────
  const [showSave, setShowSave] = useState(false);
  const [queryName, setQueryName] = useState("");
  const [queryDesc, setQueryDesc] = useState("");

  // ── Inline rename ─────────────────────────────────────────────────
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // ── Saved query click-to-execute ──────────────────────────────────
  const [activeSavedQueryId, setActiveSavedQueryId] = useState<number | null>(null);
  const [savedQueryResult, setSavedQueryResult] = useState<QueryResult | null>(null);
  const [savedQueryError, setSavedQueryError] = useState<string | null>(null);
  const [savedQueryLoading, setSavedQueryLoading] = useState(false);

  // ── Edit query state ──────────────────────────────────────────────
  const [editingQuery, setEditingQuery] = useState<SavedQuery | null>(null);

  // ── Query execution result ────────────────────────────────────────
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);

  // ── Datasource click-to-view result ───────────────────────────────
  const [dsResult, setDsResult] = useState<QueryResult | null>(null);
  const [dsError, setDsError] = useState<string | null>(null);
  const [dsLoading, setDsLoading] = useState(false);
  const [activeDsName, setActiveDsName] = useState<string | null>(null);

  // ── Member assignment ─────────────────────────────────────────────
  const [addUserId, setAddUserId] = useState<number | null>(null);
  const [addRole, setAddRole] = useState("viewer");

  // ── Data fetching ─────────────────────────────────────────────────

  const projectQuery = useQuery<Project>({
    queryKey: ["project", projectId],
    queryFn: () => apiClient.get<Project>(`/api/projects/${projectId}`),
  });

  const datasourcesQuery = useQuery<Datasource[]>({
    queryKey: ["project-datasources", projectId],
    queryFn: () => apiClient.get<Datasource[]>(`/api/projects/${projectId}/datasources`),
  });

  const queriesQuery = useQuery<SavedQuery[]>({
    queryKey: ["project-queries", projectId],
    queryFn: () => apiClient.get<SavedQuery[]>(`/api/projects/${projectId}/queries`),
  });

  const membersQuery = useQuery<Member[]>({
    queryKey: ["project-members", projectId],
    queryFn: () => apiClient.get<Member[]>(`/api/projects/${projectId}/members`),
  });

  const tenantUsersQuery = useQuery<TenantUser[]>({
    queryKey: ["tenant-users", meta?.tenant_id],
    queryFn: () =>
      apiClient.get<TenantUser[]>(`/api/tenants/${meta?.tenant_id}/users`),
    enabled: activeTab === "members" && !!meta?.tenant_id,
  });

  // ── Sharing mutations ─────────────────────────────────────────────

  const toggleShareMutation = useMutation({
    mutationFn: (share: boolean) =>
      apiClient.put<Project>(`/api/projects/${projectId}`, { is_shared: share }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] });
    },
  });

  // ── Scoping toggle mutation ──────────────────────────────────────
  const [scopingLoading, setScopingLoading] = useState(false);
  const toggleScopingMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      const result = await apiClient.put<Project>(`/api/projects/${projectId}`, { scoping_enabled: enabled });
      if (enabled) {
        setScopingLoading(true);
        try {
          await apiClient.post(`/api/ai/project/scope-map/auto-create`, { project_id: projectId });
        } catch {
          console.warn("Auto scope creation failed — scoping enabled but no scopes created");
        } finally {
          setScopingLoading(false);
        }
      }
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  // ── Saved query mutations ─────────────────────────────────────────

  const createQueryMutation = useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      left_datasource: string;
      right_datasource: string;
      join_type: string;
      left_column: string;
      right_column: string;
      sql_text: string;
    }) => apiClient.post(`/api/projects/${projectId}/queries`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setBuildingQuery(false);
      setLeftDs(null);
      setRightDs(null);
      setShowSave(false);
      setShowJoinDialog(false);
      setQueryName("");
      setQueryDesc("");
    },
  });

  const renameQueryMutation = useMutation({
    mutationFn: ({ queryId, name }: { queryId: number; name: string }) =>
      apiClient.put(`/api/projects/${projectId}/queries/${queryId}`, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setRenamingId(null);
    },
  });

  const updateQueryMutation = useMutation({
    mutationFn: (payload: {
      queryId: number;
      name?: string;
      description?: string;
      left_datasource?: string;
      right_datasource?: string;
      join_type?: string;
      left_column?: string;
      right_column?: string;
      sql_text?: string;
    }) => {
      const { queryId, ...body } = payload;
      return apiClient.put<SavedQuery>(`/api/projects/${projectId}/queries/${queryId}`, body);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setEditingQuery(null);
      // If this query's results are currently displayed, re-run it with the
      // updated SQL so changes (e.g. a removed join) are reflected immediately.
      if (data && activeSavedQueryId === variables.queryId) {
        setSavedQueryLoading(true);
        setSavedQueryError(null);
        setSavedQueryResult(null);
        apiClient
          .post<QueryResult>("/api/query/datasource", {
            tableName: data.left_datasource ?? "",
            limit: 100,
            project_id: projectId,
            sql: data.sql_text || undefined,
          })
          .then((result) => setSavedQueryResult(result))
          .catch((err) => setSavedQueryError((err as Error).message))
          .finally(() => setSavedQueryLoading(false));
      }
    },
  });

  const deleteQueryMutation = useMutation({
    mutationFn: (queryId: number) =>
      apiClient.delete(`/api/projects/${projectId}/queries/${queryId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] }),
  });

  // ── Member mutations ──────────────────────────────────────────────

  const addMemberMutation = useMutation({
    mutationFn: (payload: { user_id: number; role: string }) =>
      apiClient.post(`/api/projects/${projectId}/members`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] });
      setAddUserId(null);
    },
  });

  const updateMemberRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      apiClient.put(`/api/projects/${projectId}/members/${userId}/role`, { role }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  const deactivateMemberMutation = useMutation({
    mutationFn: (userId: number) =>
      apiClient.put(`/api/projects/${projectId}/members/${userId}/deactivate`, {}),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  const deleteMemberMutation = useMutation({
    mutationFn: (userId: number) =>
      apiClient.delete(`/api/projects/${projectId}/members/${userId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  // ── Column fetching ───────────────────────────────────────────────

  const fetchColumns = useCallback(async (viewName: string): Promise<string[]> => {
    try {
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: viewName,
        limit: 1,
        project_id: projectId,
      });
      return result.columns;
    } catch {
      return [];
    }
  }, []);

  // ── Click-to-execute saved query ─────────────────────────────────

  const executeSavedQuery = useCallback(async (q: SavedQuery) => {
    if (activeSavedQueryId === q.id) {
      setActiveSavedQueryId(null);
      setSavedQueryResult(null);
      setSavedQueryError(null);
      return;
    }
    setActiveSavedQueryId(q.id);
    setSavedQueryLoading(true);
    setSavedQueryError(null);
    setSavedQueryResult(null);
    try {
      const tableName = q.left_datasource ?? "";
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName,
        limit: 100,
        project_id: projectId,
        sql: q.sql_text || undefined,
      });
      setSavedQueryResult(result);
    } catch (err) {
      setSavedQueryError((err as Error).message);
    } finally {
      setSavedQueryLoading(false);
    }
  }, [activeSavedQueryId]);

  // ── Click-to-view datasource ──────────────────────────────────────

  const viewDatasource = useCallback(async (ds: Datasource) => {
    if (activeDsName === ds.viewName) {
      setActiveDsName(null);
      setDsResult(null);
      setDsError(null);
      return;
    }
    setActiveDsName(ds.viewName);
    setDsLoading(true);
    setDsError(null);
    setDsResult(null);
    try {
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: ds.viewName,
        limit: 100,
        project_id: projectId,
      });
      setDsResult(result);
    } catch (err) {
      setDsError((err as Error).message);
    } finally {
      setDsLoading(false);
    }
  }, [activeDsName]);

  const [dsActionError, setDsActionError] = useState<string | null>(null);
  const [showAddDs, setShowAddDs] = useState(false);

  // ── File data source actions (item 1 archive, item 3 project link) ──
  const isFileSource = useCallback(
    (ds: Datasource) => ds.id == null && !!ds.viewName,
    [],
  );

  // Unified "remove from project" for files, databases and SaaS sources
  // (item 3). Only clears the project association; gated server-side to a
  // project admin or the datasource owner.
  const removeDatasourceFromProject = useCallback(
    async (ds: Datasource) => {
      if (
        !window.confirm(
          `Remove "${ds.fileName}" from this project? It stays in the owner's datasources.`,
        )
      ) {
        return;
      }
      setDsActionError(null);
      try {
        await apiClient.post(`/api/projects/${projectId}/datasources/remove`, {
          kind: ds.id != null ? "db" : "file",
          id: ds.id ?? undefined,
          viewName: ds.viewName,
        });
        queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] });
      } catch (err) {
        setDsActionError((err as Error).message);
      }
    },
    [queryClient, projectId],
  );

  // Item 5: drag a file onto a file datasource row to replace its data.
  const [dragOverView, setDragOverView] = useState<string | null>(null);
  const [replaceMsg, setReplaceMsg] = useState<string | null>(null);
  // Item 6: confirm before overwriting an existing datasource.
  const [pendingReplace, setPendingReplace] = useState<
    { ds: Datasource; file: File } | null
  >(null);
  const replaceFileFromDrop = useCallback(
    (ds: Datasource, files: FileList | null) => {
      setDragOverView(null);
      if (!files || files.length === 0) return;
      setDsActionError(null);
      setReplaceMsg(null);
      setPendingReplace({ ds, file: files[0] });
    },
    [],
  );
  const confirmReplace = useCallback(async () => {
    if (!pendingReplace) return;
    const { ds, file } = pendingReplace;
    setPendingReplace(null);
    setDsActionError(null);
    setReplaceMsg(null);
    try {
      const res = await apiClient.upload<{ addedColumns?: string[] }>(
        `/api/upload/datasources/${encodeURIComponent(ds.viewName)}/replace`,
        file,
      );
      const added = res.addedColumns ?? [];
      setReplaceMsg(
        `Replaced "${ds.fileName}"${added.length ? ` (added: ${added.join(", ")})` : ""}.`,
      );
      queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] });
    } catch (err) {
      setDsActionError((err as Error).message);
    }
  }, [pendingReplace, queryClient, projectId]);

  // ── Drag-and-drop handlers ────────────────────────────────────────

  const handleDragStart = useCallback(
    (e: DragEvent<HTMLDivElement>, ds: Datasource) => {
      e.dataTransfer.setData("application/json", JSON.stringify(ds));
      e.dataTransfer.effectAllowed = "copy";
    },
    []
  );

  const handleDropLeft = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const data = e.dataTransfer.getData("application/json");
      if (!data) return;
      const ds: Datasource = JSON.parse(data);
      setLeftDs(ds);
      const cols = await fetchColumns(ds.viewName);
      setLeftCols(cols);
      if (rightDs) setShowJoinDialog(true);
    },
    [rightDs, fetchColumns]
  );

  const handleDropRight = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const data = e.dataTransfer.getData("application/json");
      if (!data) return;
      const ds: Datasource = JSON.parse(data);
      setRightDs(ds);
      const cols = await fetchColumns(ds.viewName);
      setRightCols(cols);
      if (leftDs) setShowJoinDialog(true);
    },
    [leftDs, fetchColumns]
  );

  const allowDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  // ── Build SQL from query config ───────────────────────────────────

  const allAvailableCols = useMemo(() => {
    const cols: string[] = [];
    if (leftDs) {
      leftCols.forEach((c) => cols.push(leftDs.viewName + "." + c));
    }
    if (rightDs) {
      rightCols.forEach((c) => cols.push(rightDs.viewName + "." + c));
    }
    return cols;
  }, [leftDs, rightDs, leftCols, rightCols]);

  const generatedSql = useMemo(() => {
    if (!leftDs) return "";
    const l = `"${leftDs.viewName}"`;
    const fieldList = selectedFields.length > 0
      ? selectedFields.map((f) => {
          const [tbl, col] = f.split(".");
          return `"${tbl}"."${col}"`;
        }).join(", ")
      : "*";

    let sql: string;
    if (!rightDs) {
      sql = `SELECT ${fieldList} FROM ${l}`;
    } else {
      const r = `"${rightDs.viewName}"`;
      if (joinType === "CROSS JOIN") {
        sql = `SELECT ${fieldList} FROM ${l} ${joinType} ${r}`;
      } else if (leftCol && rightCol) {
        sql = `SELECT ${fieldList} FROM ${l} ${joinType} ${r} ON ${l}."${leftCol}" = ${r}."${rightCol}"`;
      } else {
        return "";
      }
    }

    if (filters.length > 0) {
      const whereClauses = filters
        .filter((f) => f.column && f.operand && f.value)
        .map((f) => {
          const [tbl, col] = f.column.split(".");
          const qualCol = `"${tbl}"."${col}"`;
          if (f.operand === "IN") {
            const vals = f.value.split(",").map((v) => `'${v.trim()}'`).join(", ");
            return `${qualCol} IN (${vals})`;
          }
          if (f.operand === "LIKE") {
            return `${qualCol} LIKE '${f.value}'`;
          }
          if (f.operand === "BEGINS WITH") {
            return `${qualCol} LIKE '${f.value}%'`;
          }
          if (f.operand === "ENDS WITH") {
            return `${qualCol} LIKE '%${f.value}'`;
          }
          return `${qualCol} ${f.operand} '${f.value}'`;
        });
      if (whereClauses.length > 0) {
        sql += " WHERE " + whereClauses.join(" AND ");
      }
    }
    if (mainGroupBy.length > 0) {
      const groups = mainGroupBy.map((f) => { const [tbl, col] = f.split("."); return `"${tbl}"."${col}"`; });
      sql += " GROUP BY " + groups.join(", ");
    }
    if (mainOrderBy.length > 0) {
      const orders = mainOrderBy.map((o) => { const [tbl, col] = o.column.split("."); return `"${tbl}"."${col}" ${o.dir}`; });
      sql += " ORDER BY " + orders.join(", ");
    }
    return sql;
  }, [leftDs, rightDs, joinType, leftCol, rightCol, selectedFields, filters, mainGroupBy, mainOrderBy]);

  // ── Execute query ─────────────────────────────────────────────────

  const executeQuery = useCallback(
    async (sql: string) => {
      setExecuting(true);
      setQueryError(null);
      setQueryResult(null);
      try {
        const result = await apiClient.post<QueryResult>("/api/query/datasource", {
          tableName: leftDs?.viewName ?? "",
          limit: 100,
          project_id: projectId,
          sql,
        });
        setQueryResult(result);
      } catch (err) {
        setQueryError((err as Error).message);
      } finally {
        setExecuting(false);
      }
    },
    [leftDs, projectId]
  );

  // ── Permission checks ────────────────────────────────────────────

  const project = projectQuery.data;
  const isOwner = project?.owner_id === meta?.user_id;
  const isTenantAdmin = meta?.role === "admin";
  const myMembership = (membersQuery.data ?? []).find((m) => m.user_id === meta?.user_id);
  const myProjectRole = isOwner ? "owner" : (myMembership?.role ?? "viewer");
  const canManageMembers = isOwner || myProjectRole === "admin";
  const canEdit = isOwner || myProjectRole === "admin" || myProjectRole === "editor";
  // Item 3: only a project admin/owner (or tenant admin) — or the datasource's
  // own owner — may remove a datasource from the project.
  const isProjectAdmin = isOwner || myProjectRole === "admin" || isTenantAdmin;

  // ── Available users for member assignment ─────────────────────────

  const existingMemberIds = useMemo(
    () => new Set((membersQuery.data ?? []).map((m) => m.user_id)),
    [membersQuery.data]
  );

  const availableUsers = useMemo(
    () => (tenantUsersQuery.data ?? []).filter((u) => !existingMemberIds.has(u.id)),
    [tenantUsersQuery.data, existingMemberIds]
  );

  // ── Split members into active / inactive ──────────────────────────

  const { activeMembers, inactiveMembers } = useMemo(() => {
    const members = membersQuery.data ?? [];
    return {
      activeMembers: members.filter((m) => m.is_active),
      inactiveMembers: members.filter((m) => !m.is_active),
    };
  }, [membersQuery.data]);

  // ── Project datasources for query builder ─────────────────────────

  const projectDatasources = datasourcesQuery.data ?? [];

  // ── Render ────────────────────────────────────────────────────────

  if (projectQuery.isLoading) return <p>Loading project...</p>;
  if (projectQuery.error)
    return (
      <div>
        <p className="text-red-600">{(projectQuery.error as Error).message}</p>
        <button onClick={() => router.push("/projects")} className="mt-2 text-sm text-brand underline">
          Back to Projects
        </button>
      </div>
    );
  if (!project) return <p>Project not found.</p>;

  return (
    <section>
      {/* Header */}
      <header className="mb-6">
        <button
          onClick={() => router.push("/projects")}
          className="mb-2 text-sm text-slate-500 hover:text-slate-700"
        >
          &larr; Back to Projects
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{project.name}</h1>
            {project.description && (
              <p className="mt-1 text-sm text-slate-500">{project.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isOwner ? (
              <button
                onClick={() => toggleShareMutation.mutate(!project.is_shared)}
                disabled={toggleShareMutation.isPending}
                className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${
                  project.is_shared ? "bg-emerald-500" : "bg-slate-300"
                } disabled:opacity-50`}
                title={project.is_shared ? "Click to unshare" : "Click to share"}
              >
                <span
                  className="inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
                  style={{ transform: project.is_shared ? "translateX(30px)" : "translateX(4px)" }}
                />
              </button>
            ) : null}
            <span className={`text-xs font-medium ${
              project.is_shared ? "text-emerald-700" : "text-slate-500"
            }`}>
              {toggleShareMutation.isPending
                ? "Updating..."
                : project.is_shared ? "Shared" : "Private"}
            </span>
            {/* Scoping toggle */}
            <div className="ml-3 h-5 w-px bg-slate-200" />
            {isOwner ? (
              <button
                onClick={() => toggleScopingMutation.mutate(!project.scoping_enabled)}
                disabled={toggleScopingMutation.isPending || scopingLoading}
                className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${
                  project.scoping_enabled ? "bg-indigo-500" : "bg-slate-300"
                } disabled:opacity-50`}
                title={project.scoping_enabled ? "Click to disable scoping" : "Click to enable scoping"}
              >
                <span
                  className="inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
                  style={{ transform: project.scoping_enabled ? "translateX(30px)" : "translateX(4px)" }}
                />
              </button>
            ) : null}
            <span className={`text-xs font-medium ${
              project.scoping_enabled ? "text-indigo-700" : "text-slate-500"
            }`}>
              {toggleScopingMutation.isPending || scopingLoading
                ? "Updating..."
                : project.scoping_enabled ? "Scopes On" : "Scopes Off"}
            </span>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-slate-100 p-1">
        {(["datasources", "queries", "dashboards", "scopes", "ai", "members"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab === "ai" ? "AI" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* ── Datasources Tab ──────────────────────────────────────── */}
      {activeTab === "datasources" && (
        <div>
          {canEdit && (
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setShowAddDs(true)}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
              >
                + Add Datasource
              </button>
            </div>
          )}
          {showAddDs && (
            <AddDatasourceModal
              projectId={projectId}
              onClose={() => setShowAddDs(false)}
              onAdded={() =>
                queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] })
              }
            />
          )}
          {replaceMsg && <p className="mb-2 text-sm text-green-600">{replaceMsg}</p>}
          {datasourcesQuery.isLoading && <p className="text-sm text-slate-500">Loading datasources...</p>}
          {projectDatasources.length === 0 && !datasourcesQuery.isLoading && (
            <p className="text-sm text-slate-400">No datasources. Upload files or connect a database table.</p>
          )}
          {projectDatasources.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setDsListOpen((v) => !v)}
                className="mb-2 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 transition-colors"
              >
                <svg className={`h-4 w-4 text-slate-400 transition-transform ${dsListOpen ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                All Datasources ({projectDatasources.length})
              </button>
            {dsListOpen && (
            <div className="grid gap-2">
              {projectDatasources.map((ds) => (
                <div
                  key={ds.viewName}
                  draggable
                  onDragStart={(e) => handleDragStart(e, ds)}
                  onDragOver={
                    isFileSource(ds)
                      ? (e) => {
                          if (e.dataTransfer.types.includes("Files")) {
                            e.preventDefault();
                            setDragOverView(ds.viewName);
                          }
                        }
                      : undefined
                  }
                  onDragLeave={
                    isFileSource(ds) ? () => setDragOverView(null) : undefined
                  }
                  onDrop={
                    isFileSource(ds)
                      ? (e) => {
                          if (e.dataTransfer.files.length > 0) {
                            e.preventDefault();
                            replaceFileFromDrop(ds, e.dataTransfer.files);
                          }
                        }
                      : undefined
                  }
                  onClick={() => viewDatasource(ds)}
                  className={`flex items-center justify-between rounded-md border px-4 py-3 cursor-pointer transition-colors ${
                    dragOverView === ds.viewName
                      ? "border-brand border-dashed bg-brand/10 ring-2 ring-brand/30"
                      : activeDsName === ds.viewName
                      ? "border-brand bg-brand/5"
                      : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-slate-900">{ds.fileName}</p>
                      <SourceBadge ds={ds} />
                    </div>
                    <p className="text-xs text-slate-400 font-mono">View: {ds.viewName}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {typeof ds.size === "number" && (
                      <span className="text-xs text-slate-400">{(ds.size / 1024).toFixed(1)} KB</span>
                    )}
                    <span className="text-xs text-slate-400">
                      {activeDsName === ds.viewName ? "Click to hide" : "Click to view"}
                    </span>
                    {(isProjectAdmin || ds.ownerId === meta?.user_id) && (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); removeDatasourceFromProject(ds); }}
                        className="text-xs font-medium text-slate-500 hover:text-slate-800"
                        title="Remove this datasource from the project (keeps it in the owner's datasources)"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            )}
            </div>
          )}
          {dsActionError && (
            <p className="mt-2 text-sm text-red-600">{dsActionError}</p>
          )}

          {/* Datasource data view */}
          {dsLoading && <p className="mt-4 text-sm text-slate-500">Loading data...</p>}
          {dsError && <p className="mt-4 text-sm text-red-600">{dsError}</p>}
          {dsResult && dsResult.rows.length > 0 && (
            <div className="mt-4">
              <DataGrid
                columns={dsResult.columns}
                rows={dsResult.rows}
                columnTypes={
                  projectDatasources.find((d) => d.viewName === activeDsName)?.columnTypes
                }
              />
            </div>
          )}
          {dsResult && dsResult.rows.length === 0 && (
            <p className="mt-4 text-sm text-slate-400">No data in this datasource.</p>
          )}
        </div>
      )}

      {/* ── Queries Tab ──────────────────────────────────────────── */}
      {activeTab === "queries" && (
        <div>
          {!buildingQuery && canEdit && (
            <div className="mb-4 flex items-start gap-4">
              <button
                onClick={() => setBuildingQuery(true)}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 whitespace-nowrap"
              >
                Create New Query
              </button>
              <div className="flex-1">
                <AIPromptBar
                  placeholder="Describe the query you want to generate…"
                  submitLabel="Generate Query"
                  onSubmit={handleAIGenerateQuery}
                  loading={aiQueryLoading}
                />
                {aiQueryError && (
                  <div className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{aiQueryError}</div>
                )}
                {aiQuerySuccess && (
                  <div className="mt-2 rounded-md bg-green-50 px-3 py-2 text-xs text-green-700">{aiQuerySuccess}</div>
                )}
              </div>
            </div>
          )}

          {/* Query Builder */}
          {buildingQuery && (
            <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-medium text-slate-900">Query Builder</h3>
                <button
                  onClick={() => {
                    setBuildingQuery(false);
                    setLeftDs(null);
                    setRightDs(null);
                    setShowJoinDialog(false);
                    setJoinMode(false);
                    setShowSave(false);
                    setSelectedFields([]);
                    setFilters([]);
                    setMainSqlEditing(false);
                    setCustomSql("");
                  }}
                  className="text-sm text-slate-500 hover:text-slate-700"
                >
                  Cancel
                </button>
              </div>

              {/* Draggable datasource list inside query builder */}
              <div className="mb-4">
                <h4 className="mb-2 text-sm font-medium text-slate-700">
                  Available Datasources
                  <span className="ml-2 text-xs text-slate-400 font-normal">
                    Drag into boxes below
                  </span>
                </h4>
                {projectDatasources.length === 0 ? (
                  <p className="text-xs text-slate-400">No datasources available. Upload files first.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {projectDatasources.map((ds) => (
                      <div
                        key={ds.viewName}
                        draggable
                        onDragStart={(e) => handleDragStart(e, ds)}
                        className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm cursor-grab active:cursor-grabbing hover:border-brand hover:bg-brand/5"
                      >
                        <span>{ds.fileName}</span>
                        <SourceBadge ds={ds} />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className={`grid gap-4 mb-4 ${joinMode ? "grid-cols-2" : "grid-cols-1"}`}>
                {/* Left box */}
                <div
                  onDrop={handleDropLeft}
                  onDragOver={allowDrop}
                  className={`flex min-h-[120px] items-center justify-center rounded-lg border-2 border-dashed p-4 transition-colors ${
                    leftDs
                      ? "border-brand bg-brand/5"
                      : "border-slate-300 hover:border-slate-400"
                  }`}
                >
                  {leftDs ? (
                    <div className="text-center">
                      <p className="text-sm font-medium text-slate-900">{leftDs.fileName}</p>
                      <p className="text-xs text-slate-400 font-mono">{leftDs.viewName}</p>
                      <button
                        onClick={() => {
                          setLeftDs(null);
                          setLeftCols([]);
                          setSelectedFields([]);
                          setFilters([]);
                          setShowJoinDialog(false);
                          setJoinMode(false);
                          setRightDs(null);
                          setRightCols([]);
                        }}
                        className="mt-2 text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-400">Drop datasource here</p>
                  )}
                </div>

                {/* Right box — only when the user has added a join */}
                {joinMode && (
                  <div
                    onDrop={handleDropRight}
                    onDragOver={allowDrop}
                    className={`flex min-h-[120px] items-center justify-center rounded-lg border-2 border-dashed p-4 transition-colors ${
                      rightDs
                        ? "border-brand bg-brand/5"
                        : "border-slate-300 hover:border-slate-400"
                    }`}
                  >
                    {rightDs ? (
                      <div className="text-center">
                        <p className="text-sm font-medium text-slate-900">{rightDs.fileName}</p>
                        <p className="text-xs text-slate-400 font-mono">{rightDs.viewName}</p>
                        <button
                          onClick={() => {
                            setRightDs(null);
                            setRightCols([]);
                            setSelectedFields((prev) => prev.filter((f) => !f.startsWith(rightDs.viewName + ".")));
                            setShowJoinDialog(false);
                          }}
                          className="mt-2 text-xs text-red-500 hover:text-red-700"
                        >
                          Remove
                        </button>
                      </div>
                    ) : (
                      <p className="text-sm text-slate-400">Drop second datasource here</p>
                    )}
                  </div>
                )}
              </div>

              {/* Add / remove join control — join info is hidden until added */}
              {leftDs && (
                <div className="mb-4">
                  {!joinMode ? (
                    <button
                      onClick={() => setJoinMode(true)}
                      className="rounded-md border border-blue-300 bg-white px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50"
                    >
                      + Add Join
                    </button>
                  ) : (
                    <button
                      onClick={() => {
                        setJoinMode(false);
                        if (rightDs) {
                          setSelectedFields((prev) => prev.filter((f) => !f.startsWith(rightDs.viewName + ".")));
                        }
                        setRightDs(null);
                        setRightCols([]);
                        setShowJoinDialog(false);
                        setLeftCol("");
                        setRightCol("");
                      }}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Remove Join
                    </button>
                  )}
                </div>
              )}

              {/* Join Parameters Dialog (only when both datasources present) */}
              {showJoinDialog && leftDs && rightDs && (
                <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
                  <h4 className="mb-3 text-sm font-semibold text-blue-900">
                    Join Configuration
                  </h4>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Left Column ({leftDs.fileName})
                      </label>
                      <select
                        value={leftCol}
                        onChange={(e) => setLeftCol(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="">Select column...</option>
                        {leftCols.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Join Type
                      </label>
                      <select
                        value={joinType}
                        onChange={(e) => setJoinType(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        {JOIN_TYPES.map((jt) => (
                          <option key={jt.value} value={jt.value}>{jt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Right Column ({rightDs.fileName})
                      </label>
                      <select
                        value={rightCol}
                        onChange={(e) => setRightCol(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="">Select column...</option>
                        {rightCols.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Field Selection — collapsible */}
              {leftDs && allAvailableCols.length > 0 && (
                <div className="mb-4 rounded-lg border border-slate-200 bg-white">
                  <div className="flex items-center justify-between px-4 py-2">
                    <button
                      type="button"
                      onClick={() => setBuilderFieldsOpen((o) => !o)}
                      className="flex items-center gap-2 text-sm font-semibold text-slate-900"
                    >
                      <span className="text-slate-400">{builderFieldsOpen ? "▲" : "▼"}</span>
                      Select Fields
                      <span className="text-xs font-normal text-slate-400">
                        ({selectedFields.length === 0 ? "all" : selectedFields.length} selected)
                      </span>
                    </button>
                    {builderFieldsOpen && (
                      <div className="flex gap-2">
                        <button
                          onClick={() => setSelectedFields([...allAvailableCols])}
                          className="text-xs text-blue-600 hover:text-blue-800"
                        >
                          Select All
                        </button>
                        <button
                          onClick={() => setSelectedFields([])}
                          className="text-xs text-slate-500 hover:text-slate-700"
                        >
                          Clear
                        </button>
                      </div>
                    )}
                  </div>
                  {builderFieldsOpen && (
                    <div className="border-t border-slate-100 p-4">
                      <div className="flex flex-wrap gap-2">
                        {allAvailableCols.map((col) => {
                          const on = selectedFields.length === 0 || selectedFields.includes(col);
                          return (
                            <button
                              key={col}
                              type="button"
                              onClick={() => {
                                setSelectedFields((prev) => {
                                  const base = prev.length === 0 ? [...allAvailableCols] : prev;
                                  const next = base.includes(col)
                                    ? base.filter((f) => f !== col)
                                    : [...base, col];
                                  if (next.length === allAvailableCols.length) return [];
                                  return next;
                                });
                              }}
                              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors ${
                                on
                                  ? "border-blue-500 bg-blue-500 text-white"
                                  : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100"
                              }`}
                            >
                              <span>{col.split(".")[1]}</span>
                              {rightDs && (
                                <span className={on ? "text-blue-100" : "text-slate-400"}>({col.split(".")[0]})</span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                      <p className="mt-1 text-xs text-slate-400">
                        {selectedFields.length === 0 ? "All fields selected (SELECT *)" : `${selectedFields.length} field(s) selected`}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* + Add Filter / + Group By / + Order By buttons */}
              {leftDs && allAvailableCols.length > 0 && (
                <div className="mb-4 flex gap-2">
                  {filters.length === 0 && (
                    <button
                      onClick={() => setFilters((prev) => [...prev, { column: "", operand: "=", value: "" }])}
                      className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                    >
                      + Add Filter
                    </button>
                  )}
                  {mainGroupBy.length === 0 && (
                    <button
                      onClick={() => setMainGroupBy([""])}
                      className="rounded-md border border-purple-200 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700 hover:bg-purple-100"
                    >
                      + Group By
                    </button>
                  )}
                  {mainOrderBy.length === 0 && (
                    <button
                      onClick={() => setMainOrderBy([{ column: "", dir: "ASC" }])}
                      className="rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100"
                    >
                      + Order By
                    </button>
                  )}
                </div>
              )}

              {/* Group By field chips (Create Query) */}
              {leftDs && allAvailableCols.length > 0 && mainGroupBy.length > 0 && (
                <div className="mb-4 rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-700">Group By</span>
                    <button type="button" onClick={() => setMainGroupBy([])} className="text-xs text-red-500 hover:text-red-700">Clear</button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {allAvailableCols.map((f) => {
                      const col = f.split(".")[1] ?? f;
                      const on = mainGroupBy.includes(f);
                      return (
                        <button key={f} type="button"
                          onClick={() => setMainGroupBy((p) => on ? p.filter((x) => x !== f) : [...p.filter(Boolean), f])}
                          className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors ${on ? "border-purple-500 bg-purple-500 text-white" : "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100"}`}
                        >{col}</button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Order By field chips (Create Query) */}
              {leftDs && allAvailableCols.length > 0 && mainOrderBy.length > 0 && (
                <div className="mb-4 rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-700">Order By</span>
                    <button type="button" onClick={() => setMainOrderBy([])} className="text-xs text-red-500 hover:text-red-700">Clear</button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {allAvailableCols.map((f) => {
                      const col = f.split(".")[1] ?? f;
                      const idx = mainOrderBy.findIndex((o) => o.column === f);
                      const on = idx >= 0;
                      const dir = on ? mainOrderBy[idx].dir : "ASC";
                      return (
                        <button key={f} type="button"
                          onClick={() => {
                            if (!on) { setMainOrderBy((p) => [...p.filter((x) => x.column), { column: f, dir: "ASC" }]); }
                            else if (dir === "ASC") { setMainOrderBy((p) => p.map((x) => x.column === f ? { ...x, dir: "DESC" } : x)); }
                            else { setMainOrderBy((p) => p.filter((x) => x.column !== f)); }
                          }}
                          className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors ${on ? "border-amber-500 bg-amber-500 text-white" : "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100"}`}
                        >{col}{on ? (dir === "ASC" ? " ↑" : " ↓") : ""}</button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Filters — expanded once a filter is added */}
              {leftDs && allAvailableCols.length > 0 && filters.length > 0 && (
                <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold text-slate-900">Filters</h4>
                    <button
                      onClick={() => setFilters((prev) => [...prev, { column: "", operand: "=", value: "" }])}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      + Add Filter
                    </button>
                  </div>
                  {filters.map((f, idx) => (
                    <div key={idx} className="flex items-center gap-2 mb-2">
                      <select
                        value={f.column}
                        onChange={(e) => {
                          const updated = [...filters];
                          updated[idx] = { ...updated[idx], column: e.target.value };
                          setFilters(updated);
                        }}
                        className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="">Column...</option>
                        {allAvailableCols.map((c) => (
                          <option key={c} value={c}>{c.split(".")[1]}{rightDs ? ` (${c.split(".")[0]})` : ""}</option>
                        ))}
                      </select>
                      <select
                        value={f.operand}
                        onChange={(e) => {
                          const updated = [...filters];
                          updated[idx] = { ...updated[idx], operand: e.target.value };
                          setFilters(updated);
                        }}
                        className="w-28 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="=">=</option>
                        <option value="!=">!=</option>
                        <option value=">">&gt;</option>
                        <option value="<">&lt;</option>
                        <option value=">=">&gt;=</option>
                        <option value="<=">&lt;=</option>
                        <option value="LIKE">LIKE</option>
                        <option value="IN">IN</option>
                        <option value="BEGINS WITH">BEGINS WITH</option>
                        <option value="ENDS WITH">ENDS WITH</option>
                      </select>
                      <input
                        type="text"
                        value={f.value}
                        onChange={(e) => {
                          const updated = [...filters];
                          updated[idx] = { ...updated[idx], value: e.target.value };
                          setFilters(updated);
                        }}
                        placeholder={f.operand === "IN" ? "val1, val2, ..." : "Value"}
                        className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      />
                      <button
                        onClick={() => setFilters((prev) => prev.filter((_, i) => i !== idx))}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* SQL Preview + Actions */}
              {leftDs && (
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs font-medium text-slate-600">SQL</label>
                    <button
                      type="button"
                      onClick={() => {
                        if (mainSqlEditing) {
                          setCustomSql("");
                          setMainSqlEditing(false);
                        } else {
                          setCustomSql(generatedSql);
                          setMainSqlEditing(true);
                        }
                      }}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      {mainSqlEditing ? "Reset to generated" : "Edit SQL directly"}
                    </button>
                  </div>
                  {mainSqlEditing ? (
                    <textarea
                      value={customSql}
                      onChange={(e) => setCustomSql(e.target.value)}
                      rows={3}
                      className="w-full rounded-md border border-blue-400 bg-white px-2 py-1.5 text-xs font-mono text-slate-900 mb-3"
                    />
                  ) : (
                    generatedSql && (
                      <div className="mb-3 rounded bg-slate-800 p-3">
                        <p className="text-xs font-mono text-slate-300 break-all">{generatedSql}</p>
                      </div>
                    )
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={() => setShowSave(true)}
                      disabled={!(mainSqlEditing ? customSql : generatedSql)}
                      className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => executeQuery(mainSqlEditing ? customSql : generatedSql)}
                      disabled={!(mainSqlEditing ? customSql : generatedSql) || executing}
                      className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {executing ? "Executing..." : "Execute"}
                    </button>
                  </div>
                </div>
              )}

              {/* Save Dialog */}
              {showSave && (
                <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
                  <h4 className="mb-3 text-sm font-semibold text-slate-900">Save Query</h4>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Query Name
                      </label>
                      <input
                        type="text"
                        value={queryName}
                        onChange={(e) => setQueryName(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                        placeholder="My Query"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Description
                      </label>
                      <textarea
                        value={queryDesc}
                        onChange={(e) => setQueryDesc(e.target.value)}
                        rows={2}
                        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                        placeholder="Optional description"
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          createQueryMutation.mutate({
                            name: queryName,
                            description: queryDesc,
                            left_datasource: leftDs?.viewName ?? "",
                            right_datasource: rightDs?.viewName ?? "",
                            join_type: joinType,
                            left_column: leftCol,
                            right_column: rightCol,
                            sql_text: mainSqlEditing ? customSql : generatedSql,
                          });
                        }}
                        disabled={!queryName.trim() || createQueryMutation.isPending}
                        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
                      >
                        {createQueryMutation.isPending ? "Saving..." : "Save Query"}
                      </button>
                      <button
                        onClick={() => setShowSave(false)}
                        className="rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Execution results */}
              {queryError && <p className="text-sm text-red-600 mb-4">{queryError}</p>}
              {queryResult && queryResult.rows.length > 0 && (
                <DataGrid columns={queryResult.columns} rows={queryResult.rows} />
              )}
            </div>
          )}

          {/* Saved queries list */}
          {queriesQuery.isLoading && <p className="text-sm text-slate-500">Loading queries...</p>}
          {queriesQuery.data && queriesQuery.data.length === 0 && !buildingQuery && (
            <p className="text-sm text-slate-400">No saved queries yet.</p>
          )}
          {queriesQuery.data && queriesQuery.data.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setQueryListOpen((v) => !v)}
                className="mb-2 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 transition-colors"
              >
                <svg className={`h-4 w-4 text-slate-400 transition-transform ${queryListOpen ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                All Queries ({queriesQuery.data.length})
              </button>
            {queryListOpen && (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
              {queriesQuery.data.map((q) => (
                <li key={q.id} className="px-4 py-3">
                  <div
                    className={`flex items-center justify-between cursor-pointer rounded-md px-2 py-1 transition-colors ${
                      activeSavedQueryId === q.id
                        ? "bg-brand/5"
                        : "hover:bg-slate-50"
                    }`}
                    onClick={() => {
                      if (renamingId !== q.id) executeSavedQuery(q);
                    }}
                  >
                    {renamingId === q.id ? (
                      <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              renameQueryMutation.mutate({ queryId: q.id, name: renameValue });
                            } else if (e.key === "Escape") {
                              setRenamingId(null);
                            }
                          }}
                          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                          autoFocus
                        />
                        <button
                          onClick={() => renameQueryMutation.mutate({ queryId: q.id, name: renameValue })}
                          className="text-xs text-brand hover:text-brand/80"
                        >
                          Save
                        </button>
                      </div>
                    ) : (
                      <div
                        onDoubleClick={(e) => {
                          e.stopPropagation();
                          setRenamingId(q.id);
                          setRenameValue(q.name);
                        }}
                        title="Click to run query, double-click to rename"
                      >
                        <p className="text-sm font-medium text-slate-900">{q.name}</p>
                        {q.description && <p className="text-xs text-slate-500">{q.description}</p>}
                        {/* SQL preview removed for cleaner UI */}
                      </div>
                    )}
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <span className="text-xs text-slate-400">
                        {q.join_type ?? "N/A"}
                      </span>
                      {canEdit && (
                        <button
                          onClick={() => setEditingQuery(editingQuery?.id === q.id ? null : q)}
                          className="text-xs text-blue-600 hover:text-blue-800"
                        >
                          Edit
                        </button>
                      )}
                      {canEdit && (
                        <button
                          onClick={() => {
                            if (confirm("Delete this query?")) {
                              deleteQueryMutation.mutate(q.id);
                            }
                          }}
                          className="text-xs text-red-500 hover:text-red-700"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Inline edit form */}
                  {editingQuery?.id === q.id && (
                    <EditQueryForm
                      query={editingQuery}
                      datasources={projectDatasources}
                      projectId={projectId}
                      onSave={(updates) => updateQueryMutation.mutate({ queryId: q.id, ...updates })}
                      onCancel={() => setEditingQuery(null)}
                      isPending={updateQueryMutation.isPending}
                    />
                  )}

                  {/* Saved query results rendered underneath */}
                  {activeSavedQueryId === q.id && (
                    <div className="mt-3 ml-2">
                      {savedQueryLoading && (
                        <p className="text-sm text-slate-500">Executing query...</p>
                      )}
                      {savedQueryError && (
                        <p className="text-sm text-red-600">{savedQueryError}</p>
                      )}
                      {savedQueryResult && savedQueryResult.rows.length > 0 && (
                        <TanStackDataGrid
                          columns={savedQueryResult.columns}
                          rows={savedQueryResult.rows}
                          queryId={q.id}
                          queryName={q.name}
                          projectId={projectId}
                          availableQueries={(queriesQuery.data ?? []).map((sq) => ({
                            id: sq.id,
                            name: sq.name,
                            sql: sq.sql_text,
                            leftDatasource: sq.left_datasource,
                          }))}
                          canEditScopes={canEdit}
                          scopeEnabled={project?.scoping_enabled ?? false}
                        />
                      )}
                      {savedQueryResult && savedQueryResult.rows.length === 0 && (
                        <p className="text-sm text-slate-400">Query returned no results.</p>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            )}
            </div>
          )}
        </div>
      )}

      {/* ── Dashboards Tab ────────────────────────────────────────── */}
      {activeTab === "dashboards" && (
        <DashboardTab
          projectId={projectId}
          savedQueries={(queriesQuery.data ?? []).map((q) => ({
            id: q.id,
            name: q.name,
            sql_text: q.sql_text,
          }))}
          datasources={projectDatasources.map((ds) => ({
            viewName: ds.viewName,
            fileName: ds.fileName,
          }))}
          canEdit={canEdit}
        />
      )}

      {/* ── Scopes Tab ────────────────────────────────────────── */}
      {activeTab === "scopes" && (
        <ScopesTab projectId={projectId} />
      )}

      {/* ── AI Tab ──────────────────────────────────────────────── */}
      {activeTab === "ai" && (
        <AIPanel projectId={projectId} />
      )}

      {/* ── Members Tab ──────────────────────────────────────────── */}
      {activeTab === "members" && (
        <div>
          {canManageMembers && (
            <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-semibold text-slate-900">
                Assign Users
              </h3>
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-slate-600 mb-1">User</label>
                  <select
                    value={addUserId ?? ""}
                    onChange={(e) => setAddUserId(Number(e.target.value) || null)}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="">Select user...</option>
                    {availableUsers.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.email} {u.display_name ? `(${u.display_name})` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="w-32">
                  <label className="block text-xs font-medium text-slate-600 mb-1">Role</label>
                  <select
                    value={addRole}
                    onChange={(e) => setAddRole(e.target.value)}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <button
                  onClick={() => {
                    if (addUserId) {
                      addMemberMutation.mutate({ user_id: addUserId, role: addRole });
                    }
                  }}
                  disabled={!addUserId || addMemberMutation.isPending}
                  className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          {membersQuery.isLoading && <p className="text-sm text-slate-500">Loading members...</p>}

          {/* Active Members */}
          {activeMembers.length > 0 && (
            <div className="mb-4">
              <h4 className="mb-2 text-sm font-semibold text-slate-600">Active Members</h4>
              <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
                {activeMembers.map((m) => (
                  <li key={m.user_id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{m.email}</p>
                      {m.display_name && (
                        <p className="text-xs text-slate-500">{m.display_name}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {canManageMembers && m.role !== "owner" ? (
                        <select
                          value={m.role}
                          onChange={(e) => updateMemberRoleMutation.mutate({ userId: m.user_id, role: e.target.value })}
                          className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-700 cursor-pointer hover:border-slate-400"
                        >
                          <option value="viewer">Viewer</option>
                          <option value="editor">Editor</option>
                          <option value="admin">Admin</option>
                        </select>
                      ) : (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                          {m.role}
                        </span>
                      )}
                      {canManageMembers && m.role !== "owner" && (
                        <button
                          onClick={() => deactivateMemberMutation.mutate(m.user_id)}
                          className="text-xs text-amber-600 hover:text-amber-800"
                        >
                          Deactivate
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Inactive Members */}
          {inactiveMembers.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold text-slate-400">Inactive Members</h4>
              <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
                {inactiveMembers.map((m) => (
                  <li key={m.user_id} className="flex items-center justify-between px-4 py-3 opacity-60">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{m.email}</p>
                      {m.display_name && (
                        <p className="text-xs text-slate-500">{m.display_name}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-600">
                        inactive
                      </span>
                      {canManageMembers && (
                        <>
                          <button
                            onClick={() => addMemberMutation.mutate({ user_id: m.user_id, role: m.role })}
                            className="text-xs text-emerald-600 hover:text-emerald-800"
                          >
                            Reactivate
                          </button>
                          <button
                            onClick={() => {
                              if (confirm("Permanently remove this member? Their datasources will be moved back to their private folder.")) {
                                deleteMemberMutation.mutate(m.user_id);
                              }
                            }}
                            className="text-xs text-red-500 hover:text-red-700"
                          >
                            Remove
                          </button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeMembers.length === 0 && inactiveMembers.length === 0 && !membersQuery.isLoading && (
            <p className="text-sm text-slate-400">No members assigned yet.</p>
          )}
        </div>
      )}

      <ConfirmDialog
        open={pendingReplace !== null}
        title="Overwrite datasource?"
        message={
          pendingReplace ? (
            <>
              Are you sure you want to overwrite{" "}
              <span className="font-medium text-slate-900">
                &quot;{pendingReplace.ds.fileName}&quot;
              </span>{" "}
              with{" "}
              <span className="font-medium text-slate-900">
                &quot;{pendingReplace.file.name}&quot;
              </span>
              ? This replaces the existing data.
            </>
          ) : (
            ""
          )
        }
        confirmLabel="Yes"
        cancelLabel="Cancel"
        onConfirm={confirmReplace}
        onCancel={() => setPendingReplace(null)}
      />
    </section>
  );
}
