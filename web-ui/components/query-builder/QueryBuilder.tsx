"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { apiClient } from "@/lib/api-client";
import { DataGrid } from "@/components/data-grid/DataGrid";

// ── Types ───────────────────────────────────────────────────────────

type Datasource = {
  fileName: string;
  viewName: string;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
};

type Filter = { column: string; operand: string; value: string };
type OrderByItem = { column: string; dir: string };
type QueryResult = { columns: string[]; rows: Record<string, unknown>[] };

type SavePayload = {
  name: string;
  description: string;
  left_datasource: string;
  right_datasource: string;
  join_type: string;
  left_column: string;
  right_column: string;
  sql_text: string;
};

type EditQuery = {
  name: string;
  description: string | null;
  left_datasource: string | null;
  right_datasource: string | null;
  join_type: string | null;
  left_column: string | null;
  right_column: string | null;
  sql_text: string | null;
};

type Props = {
  projectId: number;
  datasources: Datasource[];
  onCancel: () => void;
  onSave: (payload: SavePayload) => void;
  isSaving: boolean;
  initialSql?: string;
  editQuery?: EditQuery;
  saveLabel?: string;
};

const JOIN_TYPES = [
  { value: "INNER JOIN", label: "Inner" },
  { value: "LEFT JOIN", label: "Left" },
  { value: "RIGHT JOIN", label: "Right" },
  { value: "FULL OUTER JOIN", label: "Full Outer" },
  { value: "CROSS JOIN", label: "Cross" },
];

const OPERANDS = ["=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "BEGINS WITH", "ENDS WITH"];

// ── SQL Helpers ─────────────────────────────────────────────────────

function quoteField(qualified: string): string {
  const idx = qualified.indexOf(".");
  if (idx === -1) return `"${qualified}"`;
  return `"${qualified.slice(0, idx)}"."${qualified.slice(idx + 1)}"`;
}

function unquoteField(tok: string): string {
  return tok
    .trim()
    .split(".")
    .map((p) => p.trim().replace(/^"|"$/g, ""))
    .join(".");
}

function parseSelectedFields(sql: string): string[] {
  if (!sql) return [];
  const m = /select\s+([\s\S]*?)\s+from\s/i.exec(sql);
  if (!m) return [];
  const list = m[1].trim();
  if (list === "*" || list === "") return [];
  return list
    .split(",")
    .map((tok) => {
      const cleaned = tok.trim().replace(/\s+as\s+\w+$/i, "");
      const parts = cleaned
        .split(".")
        .map((p) => p.trim().replace(/^"|"$/g, ""));
      if (parts.length >= 2) return `${parts[0]}.${parts[1]}`;
      return parts[0] || "";
    })
    .filter(Boolean);
}

function parseFromJoin(sql: string): {
  leftDs: string;
  rightDs: string;
  joinType: string;
  leftCol: string;
  rightCol: string;
} {
  const result = { leftDs: "", rightDs: "", joinType: "INNER JOIN", leftCol: "", rightCol: "" };
  if (!sql) return result;

  const fromMatch = /\sfrom\s+"?(\w+)"?/i.exec(sql) || /\sfrom\s+(\w+)/i.exec(sql);
  if (fromMatch) result.leftDs = fromMatch[1];

  const joinMatch = /\s(inner\s+join|left\s+join|right\s+join|full\s+outer\s+join|cross\s+join)\s+"?(\w+)"?/i.exec(sql);
  if (joinMatch) {
    result.joinType = joinMatch[1].toUpperCase();
    result.rightDs = joinMatch[2];
  }

  const onMatch = /\son\s+"?(\w+)"?\."?(\w+)"?\s*=\s*"?(\w+)"?\."?(\w+)"?/i.exec(sql);
  if (onMatch) {
    result.leftCol = onMatch[2];
    result.rightCol = onMatch[4];
  }

  return result;
}

function parseWhere(sql: string): Filter[] {
  const m = /\swhere\s+([\s\S]*?)(?:\s+group\s+by\s|\s+order\s+by\s|\s*$)/i.exec(sql);
  if (!m) return [];
  return m[1]
    .split(/\s+and\s+/i)
    .map((clause) => {
      const inM = /^\s*("?[\w.]+"?(?:\."?[\w]+"?)?)\s+in\s*\((.*)\)\s*$/i.exec(clause);
      if (inM) {
        const vals = inM[2].split(",").map((v) => v.trim().replace(/^'|'$/g, "")).join(", ");
        return { column: unquoteField(inM[1]), operand: "IN", value: vals };
      }
      const opM = /^\s*("?[\w.]+"?(?:\."?[\w]+"?)?)\s*(>=|<=|!=|=|>|<|like)\s*(.+?)\s*$/i.exec(clause);
      if (!opM) return null;
      return { column: unquoteField(opM[1]), operand: opM[2].toUpperCase(), value: opM[3].trim().replace(/^'|'$/g, "") };
    })
    .filter((f): f is Filter => f !== null && !!f.column);
}

function parseGroupBy(sql: string): string[] {
  const m = /\sgroup\s+by\s+([\s\S]*?)(?:\s+order\s+by\s|\s+having\s|\s*$)/i.exec(sql);
  if (!m) return [];
  return m[1].split(",").map((t) => unquoteField(t)).filter(Boolean);
}

function parseOrderBy(sql: string): OrderByItem[] {
  const m = /\sorder\s+by\s+([\s\S]*?)\s*$/i.exec(sql);
  if (!m) return [];
  return m[1]
    .split(",")
    .map((t) => {
      const parts = t.trim().split(/\s+/);
      const dir = /^(asc|desc)$/i.test(parts[parts.length - 1] ?? "") ? parts.pop()!.toUpperCase() : "ASC";
      return { column: unquoteField(parts.join(" ")), dir };
    })
    .filter((o) => !!o.column);
}

function buildSql(
  leftDs: string,
  rightDs: string,
  joinType: string,
  leftCol: string,
  rightCol: string,
  selectedFields: string[],
  filters: Filter[],
  groupBy: string[],
  orderBy: OrderByItem[],
): string {
  if (!leftDs) return "";
  const l = `"${leftDs}"`;
  const fieldList = selectedFields.length > 0
    ? selectedFields.map(quoteField).join(", ")
    : "*";

  let sql: string;
  if (!rightDs) {
    sql = `SELECT ${fieldList} FROM ${l}`;
  } else {
    const r = `"${rightDs}"`;
    if (joinType === "CROSS JOIN") {
      sql = `SELECT ${fieldList} FROM ${l} ${joinType} ${r}`;
    } else if (leftCol && rightCol) {
      sql = `SELECT ${fieldList} FROM ${l} ${joinType} ${r} ON ${l}."${leftCol}" = ${r}."${rightCol}"`;
    } else {
      return "";
    }
  }

  const whereClauses = filters
    .filter((f) => f.column && f.operand && f.value)
    .map((f) => {
      const col = quoteField(f.column);
      if (f.operand === "IN") {
        const vals = f.value.split(",").map((v) => `'${v.trim()}'`).join(", ");
        return `${col} IN (${vals})`;
      }
      if (f.operand === "LIKE") return `${col} LIKE '${f.value}'`;
      if (f.operand === "BEGINS WITH") return `${col} LIKE '${f.value}%'`;
      if (f.operand === "ENDS WITH") return `${col} LIKE '%${f.value}'`;
      return `${col} ${f.operand} '${f.value}'`;
    });
  if (whereClauses.length > 0) sql += " WHERE " + whereClauses.join(" AND ");
  const groups = groupBy.filter(Boolean).map(quoteField);
  if (groups.length > 0) sql += " GROUP BY " + groups.join(", ");
  const orders = orderBy.filter((o) => o.column).map((o) => `${quoteField(o.column)} ${o.dir}`);
  if (orders.length > 0) sql += " ORDER BY " + orders.join(", ");

  return sql;
}

// ── Component ───────────────────────────────────────────────────────

export function QueryBuilder({ projectId, datasources, onCancel, onSave, isSaving, initialSql, editQuery, saveLabel }: Props) {
  const isEdit = !!editQuery;
  // Datasource selection
  const [leftDs, setLeftDs] = useState<string>(editQuery?.left_datasource ?? "");
  const [rightDs, setRightDs] = useState<string>(editQuery?.right_datasource ?? "");
  const [leftCols, setLeftCols] = useState<string[]>([]);
  const [rightCols, setRightCols] = useState<string[]>([]);
  const [joinMode, setJoinMode] = useState(!!editQuery?.right_datasource);
  const [joinType, setJoinType] = useState(editQuery?.join_type || "INNER JOIN");
  const [leftCol, setLeftCol] = useState(editQuery?.left_column ?? "");
  const [rightCol, setRightCol] = useState(editQuery?.right_column ?? "");

  // Field selection
  const [selectedFields, setSelectedFields] = useState<string[]>(() =>
    editQuery?.sql_text ? parseSelectedFields(editQuery.sql_text) : []
  );

  // Clauses
  const [filters, setFilters] = useState<Filter[]>(() =>
    editQuery?.sql_text ? parseWhere(editQuery.sql_text) : []
  );
  const [groupBy, setGroupBy] = useState<string[]>(() =>
    editQuery?.sql_text ? parseGroupBy(editQuery.sql_text) : []
  );
  const [orderBy, setOrderBy] = useState<OrderByItem[]>(() =>
    editQuery?.sql_text ? parseOrderBy(editQuery.sql_text) : []
  );

  // SQL editing
  const [sqlText, setSqlText] = useState(editQuery?.sql_text || initialSql || "");
  const [sqlEditing, setSqlEditing] = useState(false);
  const [syncing, setSyncing] = useState(false);

  // Save form
  const [queryName, setQueryName] = useState(editQuery?.name ?? "");
  const [queryDesc, setQueryDesc] = useState(editQuery?.description ?? "");

  // Execution
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);

  // Column fetching
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
  }, [projectId]);

  useEffect(() => {
    if (leftDs) {
      fetchColumns(leftDs).then(setLeftCols);
    } else {
      setLeftCols([]);
    }
  }, [leftDs, fetchColumns]);

  useEffect(() => {
    if (rightDs) {
      fetchColumns(rightDs).then(setRightCols);
    } else {
      setRightCols([]);
    }
  }, [rightDs, fetchColumns]);

  // All available columns
  const allCols = useMemo(() => {
    const cols: string[] = [];
    if (leftDs) leftCols.forEach((c) => cols.push(`${leftDs}.${c}`));
    if (rightDs) rightCols.forEach((c) => cols.push(`${rightDs}.${c}`));
    return cols;
  }, [leftDs, rightDs, leftCols, rightCols]);

  // Generate SQL from visual state
  const generatedSql = useMemo(() => {
    return buildSql(leftDs, rightDs, joinType, leftCol, rightCol, selectedFields, filters, groupBy, orderBy);
  }, [leftDs, rightDs, joinType, leftCol, rightCol, selectedFields, filters, groupBy, orderBy]);

  // Sync SQL text when visual state changes (and not in SQL editing mode)
  useEffect(() => {
    if (!sqlEditing && !syncing && generatedSql) {
      setSqlText(generatedSql);
    }
  }, [generatedSql, sqlEditing, syncing]);

  // Parse SQL back to visual state (bidirectional sync)
  const syncFromSql = useCallback((sql: string) => {
    setSyncing(true);
    try {
      const parsed = parseFromJoin(sql);
      if (parsed.leftDs) {
        setLeftDs(parsed.leftDs);
        if (parsed.rightDs) {
          setRightDs(parsed.rightDs);
          setJoinMode(true);
          setJoinType(parsed.joinType);
          setLeftCol(parsed.leftCol);
          setRightCol(parsed.rightCol);
        }
      }
      setSelectedFields(parseSelectedFields(sql));
      setFilters(parseWhere(sql));
      setGroupBy(parseGroupBy(sql));
      setOrderBy(parseOrderBy(sql));
    } finally {
      setTimeout(() => setSyncing(false), 100);
    }
  }, []);

  // Initialize from initialSql
  useEffect(() => {
    if (initialSql) {
      syncFromSql(initialSql);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSqlBlur = useCallback(() => {
    if (sqlEditing && sqlText.trim()) {
      syncFromSql(sqlText);
    }
  }, [sqlEditing, sqlText, syncFromSql]);

  // Select/deselect datasource
  const selectDatasource = useCallback((ds: Datasource) => {
    if (!leftDs) {
      setLeftDs(ds.viewName);
    } else if (leftDs === ds.viewName) {
      setLeftDs("");
      setRightDs("");
      setJoinMode(false);
      setSelectedFields([]);
      setFilters([]);
      setGroupBy([]);
      setOrderBy([]);
      setLeftCol("");
      setRightCol("");
    } else if (joinMode) {
      if (rightDs === ds.viewName) {
        setRightDs("");
        setLeftCol("");
        setRightCol("");
      } else {
        setRightDs(ds.viewName);
      }
    } else {
      setLeftDs(ds.viewName);
      setRightDs("");
      setSelectedFields([]);
      setFilters([]);
      setGroupBy([]);
      setOrderBy([]);
    }
  }, [leftDs, rightDs, joinMode]);

  const toggleField = useCallback((field: string) => {
    setSelectedFields((prev) => {
      const base = prev.length === 0 ? [...allCols] : prev;
      const next = base.includes(field) ? base.filter((f) => f !== field) : [...base, field];
      if (next.length === allCols.length) return [];
      return next;
    });
  }, [allCols]);

  const executeQuery = useCallback(async () => {
    const sql = sqlEditing ? sqlText : generatedSql;
    if (!sql || !leftDs) return;
    setExecuting(true);
    setQueryError(null);
    setQueryResult(null);
    try {
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: leftDs,
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
  }, [sqlEditing, sqlText, generatedSql, leftDs, projectId]);

  const handleSave = useCallback(() => {
    const finalSql = sqlEditing ? sqlText : generatedSql;
    onSave({
      name: queryName,
      description: queryDesc,
      left_datasource: leftDs,
      right_datasource: rightDs,
      join_type: joinType,
      left_column: leftCol,
      right_column: rightCol,
      sql_text: finalSql,
    });
  }, [queryName, queryDesc, leftDs, rightDs, joinType, leftCol, rightCol, sqlEditing, sqlText, generatedSql, onSave]);

  const effectiveSql = sqlEditing ? sqlText : generatedSql;

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <h3 className="text-lg font-semibold text-slate-900">{isEdit ? "Edit Query" : "Query Builder"}</h3>
        <button onClick={onCancel} className="text-sm text-slate-500 hover:text-slate-700">
          Cancel
        </button>
      </div>

      <div className="p-6 space-y-5">
        {/* ── Section 1: Datasource Selection ─────────────────────── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-semibold text-slate-800">
              Datasources
              {leftDs && (
                <span className="ml-2 text-xs font-normal text-slate-400">
                  {rightDs ? "2 selected" : "1 selected"}
                </span>
              )}
            </h4>
            {leftDs && !joinMode && (
              <button
                onClick={() => setJoinMode(true)}
                className="rounded-full border border-blue-300 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
              >
                + Add Join
              </button>
            )}
            {joinMode && (
              <button
                onClick={() => {
                  setJoinMode(false);
                  setRightDs("");
                  setLeftCol("");
                  setRightCol("");
                  setSelectedFields((prev) => prev.filter((f) => !rightDs || !f.startsWith(rightDs + ".")));
                }}
                className="text-xs text-red-500 hover:text-red-700"
              >
                Remove Join
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {datasources.map((ds) => {
              const isLeft = leftDs === ds.viewName;
              const isRight = rightDs === ds.viewName;
              const isSelected = isLeft || isRight;
              return (
                <button
                  key={ds.viewName}
                  onClick={() => selectDatasource(ds)}
                  className={`group relative rounded-lg border-2 px-4 py-2.5 text-left transition-all ${
                    isLeft
                      ? "border-blue-500 bg-blue-50 ring-1 ring-blue-200"
                      : isRight
                      ? "border-emerald-500 bg-emerald-50 ring-1 ring-emerald-200"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${isSelected ? "text-slate-900" : "text-slate-700"}`}>
                      {ds.fileName}
                    </span>
                    {isLeft && (
                      <span className="rounded-full bg-blue-500 px-1.5 py-0.5 text-[9px] font-bold text-white">
                        PRIMARY
                      </span>
                    )}
                    {isRight && (
                      <span className="rounded-full bg-emerald-500 px-1.5 py-0.5 text-[9px] font-bold text-white">
                        JOIN
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[10px] font-mono text-slate-400">{ds.viewName}</p>
                </button>
              );
            })}
          </div>
          {datasources.length === 0 && (
            <p className="text-sm text-slate-400">No datasources available. Upload files or connect a database first.</p>
          )}
        </div>

        {/* ── Section 2: Join Configuration ───────────────────────── */}
        {joinMode && leftDs && (
          <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-4">
            <h4 className="mb-3 text-sm font-semibold text-blue-900">Join Configuration</h4>
            <div className="mb-3">
              <label className="mb-1.5 block text-xs font-medium text-slate-600">Join Type</label>
              <div className="flex flex-wrap gap-1.5">
                {JOIN_TYPES.map((jt) => (
                  <button
                    key={jt.value}
                    onClick={() => setJoinType(jt.value)}
                    className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                      joinType === jt.value
                        ? "border-blue-500 bg-blue-500 text-white"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {jt.label}
                  </button>
                ))}
              </div>
            </div>
            {joinType !== "CROSS JOIN" && rightDs && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-600">
                    Left Column <span className="text-slate-400">({leftDs})</span>
                  </label>
                  <div className="flex flex-wrap gap-1">
                    {leftCols.map((c) => (
                      <button
                        key={c}
                        onClick={() => setLeftCol(c)}
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          leftCol === c
                            ? "border-blue-500 bg-blue-500 text-white"
                            : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {c}
                      </button>
                    ))}
                    {leftCols.length === 0 && <span className="text-xs text-slate-400">Loading columns...</span>}
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-600">
                    Right Column <span className="text-slate-400">({rightDs})</span>
                  </label>
                  <div className="flex flex-wrap gap-1">
                    {rightCols.map((c) => (
                      <button
                        key={c}
                        onClick={() => setRightCol(c)}
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          rightCol === c
                            ? "border-emerald-500 bg-emerald-500 text-white"
                            : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {c}
                      </button>
                    ))}
                    {rightCols.length === 0 && <span className="text-xs text-slate-400">Loading columns...</span>}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Section 3: Field Selection (chips) ─────────────────── */}
        {leftDs && allCols.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-slate-800">
                Select Fields
                <span className="ml-2 text-xs font-normal text-slate-400">
                  {selectedFields.length === 0 ? "All fields (SELECT *)" : `${selectedFields.length} selected`}
                </span>
              </h4>
              <div className="flex gap-2">
                <button
                  onClick={() => setSelectedFields([])}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  Select All
                </button>
                <button
                  onClick={() => setSelectedFields(allCols.length > 0 ? [allCols[0]] : [])}
                  className="text-xs text-slate-500 hover:text-slate-700"
                >
                  Clear
                </button>
              </div>
            </div>
            <div className={rightDs ? "grid grid-cols-2 gap-4" : ""}>
              <div>
                {rightDs && (
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-blue-500">
                    {leftDs}
                  </p>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {leftCols.map((c) => {
                    const field = `${leftDs}.${c}`;
                    const on = selectedFields.length === 0 || selectedFields.includes(field);
                    return (
                      <button
                        key={c}
                        onClick={() => toggleField(field)}
                        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          on
                            ? "border-blue-500 bg-blue-500 text-white"
                            : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                      >
                        {c}
                        {on && selectedFields.length > 0 && (
                          <span className="text-blue-200">&times;</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
              {rightDs && (
                <div>
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-500">
                    {rightDs}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {rightCols.map((c) => {
                      const field = `${rightDs}.${c}`;
                      const on = selectedFields.length === 0 || selectedFields.includes(field);
                      return (
                        <button
                          key={c}
                          onClick={() => toggleField(field)}
                          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                            on
                              ? "border-emerald-500 bg-emerald-500 text-white"
                              : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                          }`}
                        >
                          {c}
                          {on && selectedFields.length > 0 && (
                            <span className="text-emerald-200">&times;</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Section 4: Filters / Group By / Order By ───────────── */}
        {leftDs && allCols.length > 0 && (
          <div className="space-y-3">
            {/* Action buttons */}
            <div className="flex gap-2">
              <button
                onClick={() => setFilters((p) => [...p, { column: "", operand: "=", value: "" }])}
                className="rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-medium text-orange-700 hover:bg-orange-100"
              >
                + Filter
              </button>
              {groupBy.length === 0 && (
                <button
                  onClick={() => setGroupBy([""])}
                  className="rounded-full border border-purple-200 bg-purple-50 px-3 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100"
                >
                  + Group By
                </button>
              )}
              {orderBy.length === 0 && (
                <button
                  onClick={() => setOrderBy([{ column: "", dir: "ASC" }])}
                  className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100"
                >
                  + Order By
                </button>
              )}
            </div>

            {/* Filters */}
            {filters.length > 0 && (
              <div className="rounded-lg border border-orange-100 bg-orange-50/50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-orange-800">Filters</span>
                  <button onClick={() => setFilters([])} className="text-xs text-red-500 hover:text-red-700">Clear All</button>
                </div>
                {filters.map((f, idx) => (
                  <div key={idx} className="mb-2 flex items-center gap-2">
                    {/* Column chips */}
                    <div className="flex-1">
                      <div className="flex flex-wrap gap-1">
                        {allCols.map((c) => {
                          const colName = c.split(".")[1] ?? c;
                          return (
                            <button
                              key={c}
                              onClick={() => setFilters((p) => p.map((x, i) => i === idx ? { ...x, column: c } : x))}
                              className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                                f.column === c
                                  ? "border-orange-500 bg-orange-500 text-white"
                                  : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                              }`}
                            >
                              {colName}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    {/* Operand chips */}
                    <div className="flex gap-0.5">
                      {OPERANDS.map((op) => (
                        <button
                          key={op}
                          onClick={() => setFilters((p) => p.map((x, i) => i === idx ? { ...x, operand: op } : x))}
                          className={`rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
                            f.operand === op
                              ? "border-orange-500 bg-orange-500 text-white"
                              : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                          }`}
                        >
                          {op}
                        </button>
                      ))}
                    </div>
                    <input
                      type="text"
                      value={f.value}
                      onChange={(e) => setFilters((p) => p.map((x, i) => i === idx ? { ...x, value: e.target.value } : x))}
                      placeholder={f.operand === "IN" ? "val1, val2, ..." : "Value"}
                      className="w-32 rounded-md border border-slate-300 px-2 py-1 text-xs"
                    />
                    <button
                      onClick={() => setFilters((p) => p.filter((_, i) => i !== idx))}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      &times;
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Group By chips */}
            {groupBy.length > 0 && (
              <div className="rounded-lg border border-purple-100 bg-purple-50/50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-purple-800">Group By</span>
                  <button onClick={() => setGroupBy([])} className="text-xs text-red-500 hover:text-red-700">Clear</button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {allCols.map((f) => {
                    const col = f.split(".")[1] ?? f;
                    const on = groupBy.includes(f);
                    return (
                      <button
                        key={f}
                        onClick={() => setGroupBy((p) => on ? p.filter((x) => x !== f) : [...p.filter(Boolean), f])}
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          on ? "border-purple-500 bg-purple-500 text-white" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                      >
                        {col}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Order By chips */}
            {orderBy.length > 0 && (
              <div className="rounded-lg border border-amber-100 bg-amber-50/50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-amber-800">Order By</span>
                  <button onClick={() => setOrderBy([])} className="text-xs text-red-500 hover:text-red-700">Clear</button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {allCols.map((f) => {
                    const col = f.split(".")[1] ?? f;
                    const idx = orderBy.findIndex((o) => o.column === f);
                    const on = idx >= 0;
                    const dir = on ? orderBy[idx].dir : "ASC";
                    return (
                      <button
                        key={f}
                        onClick={() => {
                          if (!on) setOrderBy((p) => [...p.filter((x) => x.column), { column: f, dir: "ASC" }]);
                          else if (dir === "ASC") setOrderBy((p) => p.map((x) => x.column === f ? { ...x, dir: "DESC" } : x));
                          else setOrderBy((p) => p.filter((x) => x.column !== f));
                        }}
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          on ? "border-amber-500 bg-amber-500 text-white" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                      >
                        {col}{on ? (dir === "ASC" ? " ↑" : " ↓") : ""}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Section 5: SQL Editor (bidirectional) ──────────────── */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <h4 className="text-sm font-semibold text-slate-800">SQL Statement</h4>
            <button
              onClick={() => {
                if (sqlEditing) {
                  syncFromSql(sqlText);
                  setSqlEditing(false);
                } else {
                  setSqlText(generatedSql);
                  setSqlEditing(true);
                }
              }}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              {sqlEditing ? "Sync to visual builder" : "Edit SQL directly"}
            </button>
          </div>
          <textarea
            value={sqlEditing ? sqlText : generatedSql}
            onChange={(e) => setSqlText(e.target.value)}
            onBlur={handleSqlBlur}
            readOnly={!sqlEditing}
            rows={3}
            className={`w-full rounded-lg border px-3 py-2 text-xs font-mono transition-colors ${
              sqlEditing
                ? "border-blue-400 bg-white text-slate-900 focus:ring-1 focus:ring-blue-300"
                : "border-slate-200 bg-slate-800 text-slate-300 cursor-default"
            }`}
            placeholder="SQL will be generated from your selections above..."
          />
          {sqlEditing && (
            <p className="mt-1 text-[10px] text-blue-500">
              Editing SQL directly. Click &quot;Sync to visual builder&quot; to update the visual controls from your SQL.
            </p>
          )}
        </div>

        {/* ── Section 6: Actions ─────────────────────────────────── */}
        <div className="flex items-center gap-3 pt-2 border-t border-slate-100">
          <button
            onClick={executeQuery}
            disabled={!effectiveSql || executing}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {executing ? "Executing..." : "Execute"}
          </button>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={queryName}
              onChange={(e) => setQueryName(e.target.value)}
              placeholder="Query name..."
              className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
            <input
              type="text"
              value={queryDesc}
              onChange={(e) => setQueryDesc(e.target.value)}
              placeholder="Description (optional)"
              className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
            <button
              onClick={handleSave}
              disabled={!queryName.trim() || !effectiveSql || isSaving}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
            >
              {isSaving ? "Saving..." : (saveLabel ?? (isEdit ? "Update Query" : "Save Query"))}
            </button>
          </div>
        </div>

        {/* ── Execution Results ──────────────────────────────────── */}
        {queryError && <p className="text-sm text-red-600">{queryError}</p>}
        {queryResult && queryResult.rows.length > 0 && (
          <DataGrid columns={queryResult.columns} rows={queryResult.rows} />
        )}
        {queryResult && queryResult.rows.length === 0 && (
          <p className="text-sm text-slate-400">Query returned no results.</p>
        )}
      </div>
    </div>
  );
}
