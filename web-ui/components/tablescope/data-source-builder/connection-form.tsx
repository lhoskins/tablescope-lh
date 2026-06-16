"use client";

import { useState } from "react";
import { IconLoader2 } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  useBuilderStore,
  type SessionSource,
  type SourceType,
  type TableSelection,
} from "@/lib/stores/data-source-builder-store";
import {
  listDbTables,
  testConnection,
  type ConnectionParams,
} from "@/lib/api/data-source-builder";
import { CONNECTOR_LABELS } from "./util";

const DB_TYPE_BY_SOURCE: Partial<Record<SourceType, string>> = {
  postgresql: "postgresql",
  mysql: "mysql",
  snowflake: "snowflake",
  bigquery: "bigquery",
};

const DEFAULT_PORT: Record<string, string> = {
  postgresql: "5432",
  mysql: "3306",
};

function field(
  label: string,
  value: string,
  onChange: (v: string) => void,
  opts: { type?: string; placeholder?: string; optional?: boolean } = {},
) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
        {label}
        {opts.optional && (
          <span className="ml-1 text-ink-tertiary">(optional)</span>
        )}
      </span>
      <input
        type={opts.type ?? "text"}
        value={value}
        placeholder={opts.placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
      />
    </label>
  );
}

export function ConnectionForm({
  sourceType,
  onAdded,
  onCancel,
}: {
  sourceType: SourceType;
  onAdded: () => void;
  onCancel: () => void;
}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const hasSource = useBuilderStore((s) => s.hasSource);

  const dbType = DB_TYPE_BY_SOURCE[sourceType] ?? "postgresql";
  const [host, setHost] = useState("");
  const [port, setPort] = useState(DEFAULT_PORT[dbType] ?? "");
  const [database, setDatabase] = useState("");
  const [schema, setSchema] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [ssl, setSsl] = useState(true);

  const [testing, setTesting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [tested, setTested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const params = (): ConnectionParams => ({
    db_type: dbType,
    host,
    port: port ? Number(port) : undefined,
    database_name: database,
    schema_name: schema || undefined,
    username,
    password,
    ssl_mode: ssl ? "require" : undefined,
  });

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await testConnection(params());
      if (res.success) {
        setTested(true);
        setSuccessMsg(`Connected · ${CONNECTOR_LABELS[sourceType]}`);
      } else {
        setError(res.message || "Connection failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setTesting(false);
    }
  };

  const handleAdd = async () => {
    if (hasSource((s) => !s.isFileUpload && s.displayName === database)) {
      setError("This source is already in your session.");
      return;
    }
    setAdding(true);
    setError(null);
    try {
      const tables = await listDbTables(params());
      const tableSelections: TableSelection[] = tables.map((t) => ({
        tableName: t.table_name,
        rows: 0,
        cols: 0,
        aiEnabled: true,
        state: "unselected",
      }));
      const connectionConfig: Record<string, string> = {
        db_type: dbType,
        host,
        port,
        database_name: database,
        schema_name: schema,
        username,
        password,
        ssl_mode: ssl ? "require" : "",
      };
      const source: SessionSource = {
        id: crypto.randomUUID(),
        sourceType,
        displayName: database || host || CONNECTOR_LABELS[sourceType],
        connectionConfig,
        status: "connected",
        tables: tableSelections,
        isFileUpload: false,
      };
      addSource(source);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not discover tables");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        {field("Host", host, setHost, { placeholder: "db.example.com" })}
        {field("Port", port, setPort, { placeholder: DEFAULT_PORT[dbType] })}
        {field("Database", database, setDatabase, { placeholder: "analytics" })}
        {field("Schema", schema, setSchema, {
          optional: true,
          placeholder: "public",
        })}
        {field("Username", username, setUsername)}
        {field("Password", password, setPassword, { type: "password" })}
      </div>

      <label className="flex items-center gap-2 text-[12px] text-ink-secondary">
        <input
          type="checkbox"
          checked={ssl}
          onChange={(e) => setSsl(e.target.checked)}
          className="h-4 w-4 accent-[var(--brand,#185FA5)]"
        />
        Use SSL
      </label>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger-bg/40 px-3 py-2 text-[12px] text-danger">
          {error}
        </div>
      )}
      {successMsg && !error && (
        <div className="rounded-md border border-success/40 bg-success-bg/40 px-3 py-2 text-[12px] text-success">
          {successMsg}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="secondary"
          onClick={handleTest}
          disabled={testing || !host || !database || !username}
        >
          {testing && <IconLoader2 size={14} className="animate-spin" />}
          {error ? "Retry" : "Test connection"}
        </Button>
        {tested && (
          <Button variant="primary" onClick={handleAdd} disabled={adding}>
            {adding && <IconLoader2 size={14} className="animate-spin" />}
            Add to session
          </Button>
        )}
      </div>
    </div>
  );
}
