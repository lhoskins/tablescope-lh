"use client";

import { useState, useCallback, useMemo, useEffect, DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";

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
  owner_id: number | null;
};

type Datasource = {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
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
    const cols = selectedFields.length === 0 ? "*" : selectedFields.map(quoteField).join(", ");
    if (!showJoin || !rightDs) return `SELECT ${cols} FROM ${l}`;
    const r = `"${rightDs}"`;
    if (jt === "CROSS JOIN") return `SELECT ${cols} FROM ${l} ${jt} ${r}`;
    if (!lc || !rc) return "";
    return `SELECT ${cols} FROM ${l} ${jt} ${r} ON ${l}."${lc}" = ${r}."${rc}"`;
  }, [leftDs, rightDs, jt, lc, rc, showJoin, selectedFields]);

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
                <button type="button" onClick={(e) => { e.stopPropagation(); markDirty(); setSelectedFields(allFields.length ? allFields.slice(0, 1) : []); }}
                  className="text-xs text-slate-500 hover:text-slate-700">Reset</button>
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
        <div className="mt-3 overflow-x-auto rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                {execResult.columns.map((col) => (
                  <th key={col} className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {execResult.rows.slice(0, 50).map((row, i) => (
                <tr key={i}>
                  {execResult.columns.map((col) => (
                    <td key={col} className="whitespace-nowrap px-3 py-2 text-sm text-slate-700">
                      {String(row[col] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {execResult.rows.length > 50 && (
            <p className="px-3 py-2 text-xs text-slate-400">
              Showing first 50 of {execResult.rows.length} rows
            </p>
          )}
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
  const [activeTab, setActiveTab] = useState<"datasources" | "queries" | "members">("datasources");

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
      return apiClient.put(`/api/projects/${projectId}/queries/${queryId}`, body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setEditingQuery(null);
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
          return `${qualCol} ${f.operand} '${f.value}'`;
        });
      if (whereClauses.length > 0) {
        sql += " WHERE " + whereClauses.join(" AND ");
      }
    }
    return sql;
  }, [leftDs, rightDs, joinType, leftCol, rightCol, selectedFields, filters]);

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
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-slate-100 p-1">
        {(["datasources", "queries", "members"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* ── Datasources Tab ──────────────────────────────────────── */}
      {activeTab === "datasources" && (
        <div>
          {canEdit && (
            <div className="mb-4">
              <ConnectorsMenu
                projectId={projectId}
                onCreated={() =>
                  queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] })
                }
              />
            </div>
          )}
          {datasourcesQuery.isLoading && <p className="text-sm text-slate-500">Loading datasources...</p>}
          {projectDatasources.length === 0 && !datasourcesQuery.isLoading && (
            <p className="text-sm text-slate-400">No datasources. Upload files or connect a database table.</p>
          )}
          {projectDatasources.length > 0 && (
            <div className="grid gap-2">
              {projectDatasources.map((ds) => (
                <div
                  key={ds.viewName}
                  draggable
                  onDragStart={(e) => handleDragStart(e, ds)}
                  onClick={() => viewDatasource(ds)}
                  className={`flex items-center justify-between rounded-md border px-4 py-3 cursor-pointer transition-colors ${
                    activeDsName === ds.viewName
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
                  <div className="flex items-center gap-2">
                    {typeof ds.size === "number" && (
                      <span className="text-xs text-slate-400">{(ds.size / 1024).toFixed(1)} KB</span>
                    )}
                    <span className="text-xs text-slate-400">
                      {activeDsName === ds.viewName ? "Click to hide" : "Click to view"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Datasource data view */}
          {dsLoading && <p className="mt-4 text-sm text-slate-500">Loading data...</p>}
          {dsError && <p className="mt-4 text-sm text-red-600">{dsError}</p>}
          {dsResult && dsResult.rows.length > 0 && (
            <div className="mt-4 overflow-x-auto rounded-md border border-slate-200 bg-white">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    {dsResult.columns.map((col) => (
                      <th key={col} className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {dsResult.rows.slice(0, 50).map((row, i) => (
                    <tr key={i}>
                      {dsResult.columns.map((col) => (
                        <td key={col} className="whitespace-nowrap px-3 py-2 text-sm text-slate-700">
                          {String(row[col] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {dsResult.rows.length > 50 && (
                <p className="px-3 py-2 text-xs text-slate-400">
                  Showing first 50 of {dsResult.rows.length} rows
                </p>
              )}
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
            <button
              onClick={() => setBuildingQuery(true)}
              className="mb-4 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
            >
              Create New Query
            </button>
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

              {/* Filters */}
              {leftDs && allAvailableCols.length > 0 && (
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
                  {filters.length === 0 && (
                    <p className="text-xs text-slate-400">No filters. Click &quot;+ Add Filter&quot; to add a WHERE condition.</p>
                  )}
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
                        className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="=">=</option>
                        <option value="!=">!=</option>
                        <option value=">">&gt;</option>
                        <option value="<">&lt;</option>
                        <option value=">=">&gt;=</option>
                        <option value="<=">&lt;=</option>
                        <option value="LIKE">LIKE</option>
                        <option value="IN">IN</option>
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
                <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
                  <table className="min-w-full divide-y divide-slate-200">
                    <thead className="bg-slate-50">
                      <tr>
                        {queryResult.columns.map((col) => (
                          <th key={col} className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {queryResult.rows.slice(0, 50).map((row, i) => (
                        <tr key={i}>
                          {queryResult.columns.map((col) => (
                            <td key={col} className="whitespace-nowrap px-3 py-2 text-sm text-slate-700">
                              {String(row[col] ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {queryResult.rows.length > 50 && (
                    <p className="px-3 py-2 text-xs text-slate-400">
                      Showing first 50 of {queryResult.rows.length} rows
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Saved queries list */}
          {queriesQuery.isLoading && <p className="text-sm text-slate-500">Loading queries...</p>}
          {queriesQuery.data && queriesQuery.data.length === 0 && !buildingQuery && (
            <p className="text-sm text-slate-400">No saved queries yet.</p>
          )}
          {queriesQuery.data && queriesQuery.data.length > 0 && (
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
                        {q.sql_text && (
                          <p className="mt-1 text-xs font-mono text-slate-400 truncate max-w-md">
                            {q.sql_text}
                          </p>
                        )}
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
                        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
                          <table className="min-w-full divide-y divide-slate-200">
                            <thead className="bg-slate-50">
                              <tr>
                                {savedQueryResult.columns.map((col) => (
                                  <th key={col} className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                                    {col}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {savedQueryResult.rows.slice(0, 50).map((row, i) => (
                                <tr key={i}>
                                  {savedQueryResult.columns.map((col) => (
                                    <td key={col} className="whitespace-nowrap px-3 py-2 text-sm text-slate-700">
                                      {String(row[col] ?? "")}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {savedQueryResult.rows.length > 50 && (
                            <p className="px-3 py-2 text-xs text-slate-400">
                              Showing first 50 of {savedQueryResult.rows.length} rows
                            </p>
                          )}
                        </div>
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
    </section>
  );
}
