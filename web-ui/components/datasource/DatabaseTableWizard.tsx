"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api-client";

// Connect an external database table as an independent Tablescope data source.
// Mirrors the file-upload flow but walks the user through:
//   connection -> test -> schema -> table -> column preview -> save.
// PostgreSQL, MySQL, SQL Server and Oracle are supported via bundled JDBC
// driver modules + Python DBAPI drivers for introspection.

type DbType = { value: string; label: string; defaultPort: number; enabled: boolean };

const DB_TYPES: DbType[] = [
  { value: "postgresql", label: "PostgreSQL", defaultPort: 5432, enabled: true },
  { value: "mysql", label: "MySQL", defaultPort: 3306, enabled: true },
  { value: "sqlserver", label: "SQL Server", defaultPort: 1433, enabled: true },
  { value: "oracle", label: "Oracle", defaultPort: 1521, enabled: true },
];

type TableInfo = { schema_name: string | null; table_name: string; type: string };
type ColumnInfo = {
  name: string;
  type: string | null;
  nullable: boolean | null;
  primary_key: boolean;
};

type Connection = {
  db_type: string;
  host: string;
  port: number | null;
  database_name: string;
  username: string;
  password: string;
  ssl_mode: string;
};

type Step = "connection" | "schema" | "table" | "columns";

export function DatabaseTableWizard({
  projectId,
  onClose,
  onCreated,
}: {
  projectId?: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [step, setStep] = useState<Step>("connection");
  const [conn, setConn] = useState<Connection>({
    db_type: "postgresql",
    host: "",
    port: 5432,
    database_name: "",
    username: "",
    password: "",
    ssl_mode: "",
  });

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const [schemas, setSchemas] = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<string>("");
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [displayName, setDisplayName] = useState("");

  function body(extra: Record<string, unknown> = {}) {
    return {
      db_type: conn.db_type,
      host: conn.host,
      port: conn.port,
      database_name: conn.database_name,
      username: conn.username,
      password: conn.password,
      ssl_mode: conn.ssl_mode || null,
      ...extra,
    };
  }

  async function handleTest() {
    setBusy(true);
    setError(null);
    setTestMessage(null);
    try {
      const res = await apiClient.post<{ success: boolean; message: string }>(
        "/api/database-sources/test",
        body()
      );
      if (!res.success) {
        setError(res.message);
        return;
      }
      setTestMessage(res.message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection test failed");
    } finally {
      setBusy(false);
    }
  }

  async function loadSchemas() {
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<{ schemas: string[] }>(
        "/api/database-sources/schemas",
        body()
      );
      setSchemas(res.schemas);
      setSelectedSchema(res.schemas[0] ?? "");
      setStep("schema");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load schemas");
    } finally {
      setBusy(false);
    }
  }

  async function loadTables(schema: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<{ tables: TableInfo[] }>(
        "/api/database-sources/tables",
        body({ schema_name: schema })
      );
      setTables(res.tables);
      setStep("table");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load tables");
    } finally {
      setBusy(false);
    }
  }

  async function loadColumns(t: TableInfo) {
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<{ columns: ColumnInfo[] }>(
        "/api/database-sources/columns",
        body({ schema_name: t.schema_name, table_name: t.table_name })
      );
      setColumns(res.columns);
      setSelectedTable(t);
      setDisplayName(t.table_name);
      setStep("columns");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load columns");
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (!selectedTable || !displayName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiClient.post("/api/database-sources", {
        ...body({
          schema_name: selectedTable.schema_name,
          table_name: selectedTable.table_name,
          display_name: displayName.trim(),
        }),
        project_id: projectId ?? null,
      });
      onCreated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save data source");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none";
  const label = "block text-xs font-medium text-slate-600 mb-1";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Connect Database Table</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Step indicator */}
        <div className="mb-4 flex items-center gap-2 text-xs">
          {(["connection", "schema", "table", "columns"] as Step[]).map((s, i) => (
            <span
              key={s}
              className={`rounded-full px-2 py-0.5 ${
                step === s ? "bg-brand text-brand-fg" : "bg-slate-100 text-slate-500"
              }`}
            >
              {i + 1}. {s}
            </span>
          ))}
        </div>

        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Step 1: Connection */}
        {step === "connection" && (
          <div className="space-y-3">
            <div>
              <label className={label}>Database Type</label>
              <select
                className={input}
                value={conn.db_type}
                onChange={(e) => {
                  const t = DB_TYPES.find((d) => d.value === e.target.value);
                  setConn((c) => ({ ...c, db_type: e.target.value, port: t?.defaultPort ?? c.port }));
                }}
              >
                {DB_TYPES.map((d) => (
                  <option key={d.value} value={d.value} disabled={!d.enabled}>
                    {d.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className={label}>Host</label>
                <input
                  className={input}
                  value={conn.host}
                  onChange={(e) => setConn((c) => ({ ...c, host: e.target.value }))}
                  placeholder="db.example.com"
                />
              </div>
              <div>
                <label className={label}>Port</label>
                <input
                  className={input}
                  type="number"
                  value={conn.port ?? ""}
                  onChange={(e) =>
                    setConn((c) => ({ ...c, port: e.target.value ? Number(e.target.value) : null }))
                  }
                />
              </div>
            </div>
            <div>
              <label className={label}>Database Name</label>
              <input
                className={input}
                value={conn.database_name}
                onChange={(e) => setConn((c) => ({ ...c, database_name: e.target.value }))}
                placeholder="mydb"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={label}>Username</label>
                <input
                  className={input}
                  value={conn.username}
                  onChange={(e) => setConn((c) => ({ ...c, username: e.target.value }))}
                  autoComplete="off"
                />
              </div>
              <div>
                <label className={label}>Password</label>
                <input
                  className={input}
                  type="password"
                  value={conn.password}
                  onChange={(e) => setConn((c) => ({ ...c, password: e.target.value }))}
                  autoComplete="new-password"
                />
              </div>
            </div>
            <div>
              <label className={label}>SSL Mode (optional)</label>
              <input
                className={input}
                value={conn.ssl_mode}
                onChange={(e) => setConn((c) => ({ ...c, ssl_mode: e.target.value }))}
                placeholder="require, disable, prefer..."
              />
            </div>

            {testMessage && (
              <p className="text-sm text-green-700">{testMessage}</p>
            )}

            <div className="flex justify-between pt-2">
              <button
                onClick={handleTest}
                disabled={busy || !conn.host || !conn.database_name || !conn.username}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {busy ? "Testing..." : "Test Connection"}
              </button>
              <button
                onClick={loadSchemas}
                disabled={busy || !conn.host || !conn.database_name || !conn.username}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                Next: Browse Schemas
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Schema */}
        {step === "schema" && (
          <div className="space-y-3">
            <label className={label}>Select Schema</label>
            <select
              className={input}
              value={selectedSchema}
              onChange={(e) => setSelectedSchema(e.target.value)}
            >
              {schemas.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep("connection")}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Back
              </button>
              <button
                onClick={() => loadTables(selectedSchema)}
                disabled={busy || !selectedSchema}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                Next: Browse Tables
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Table */}
        {step === "table" && (
          <div className="space-y-3">
            <label className={label}>Select a Table or View</label>
            <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200">
              {tables.length === 0 && (
                <p className="px-3 py-2 text-sm text-slate-400">No tables found in this schema.</p>
              )}
              {tables.map((t) => (
                <button
                  key={`${t.schema_name}.${t.table_name}`}
                  onClick={() => loadColumns(t)}
                  disabled={busy}
                  className="flex w-full items-center justify-between border-b border-slate-100 px-3 py-2 text-left text-sm hover:bg-slate-50 disabled:opacity-50"
                >
                  <span className="font-medium text-slate-800">{t.table_name}</span>
                  <span className="text-xs uppercase text-slate-400">{t.type}</span>
                </button>
              ))}
            </div>
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep("schema")}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Back
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Columns + Save */}
        {step === "columns" && selectedTable && (
          <div className="space-y-3">
            <div>
              <label className={label}>Data Source Name</label>
              <input
                className={input}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-slate-600">
                Columns in {selectedTable.table_name}
              </p>
              <div className="max-h-60 overflow-y-auto rounded-md border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">Column</th>
                      <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">Type</th>
                      <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">Nullable</th>
                      <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">PK</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {columns.map((c) => (
                      <tr key={c.name}>
                        <td className="px-3 py-1.5 text-sm text-slate-800">{c.name}</td>
                        <td className="px-3 py-1.5 text-sm text-slate-500">{c.type}</td>
                        <td className="px-3 py-1.5 text-sm text-slate-500">{c.nullable ? "yes" : "no"}</td>
                        <td className="px-3 py-1.5 text-sm text-slate-500">{c.primary_key ? "✓" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep("table")}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Back
              </button>
              <button
                onClick={handleSave}
                disabled={busy || !displayName.trim()}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                {busy ? "Saving..." : "Save Data Source"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
