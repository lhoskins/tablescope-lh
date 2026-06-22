"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { IconLoader2, IconPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  listDbTables,
  listSavedConnections,
  type SavedConnection,
} from "@/lib/api/data-source-builder";
import { connectorDisplayName } from "@/lib/api/connectors";
import {
  useBuilderStore,
  type SessionSource,
  type SourceType,
} from "@/lib/stores/data-source-builder-store";
import { connectorSpec } from "../database-connectors/connector-fields";

const SOURCE_TYPES = new Set<SourceType>([
  "postgresql",
  "mysql",
  "snowflake",
  "bigquery",
]);

function toSourceType(dbType: string): SourceType {
  return SOURCE_TYPES.has(dbType as SourceType)
    ? (dbType as SourceType)
    : "postgresql";
}

export function ConnectedDatabases() {
  const { data: connections, isLoading } = useQuery({
    queryKey: ["builder", "saved-connections"],
    queryFn: listSavedConnections,
  });
  const addSource = useBuilderStore((s) => s.addSource);
  const sources = useBuilderStore((s) => s.sources);
  const setActiveSource = useBuilderStore((s) => s.setActiveSource);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async (conn: SavedConnection) => {
    // If this connection already has a session source, just focus it.
    const existing = sources.find(
      (s) => s.connectionConfig.connection_id === String(conn.id),
    );
    if (existing) {
      setActiveSource(existing.id);
      return;
    }
    setBusyId(conn.id);
    setError(null);
    try {
      const tables = await listDbTables({ connection_id: conn.id });
      const source: SessionSource = {
        id: `conn-${conn.id}-${Date.now()}`,
        sourceType: toSourceType(conn.db_type),
        displayName: conn.name,
        connectionConfig: {
          connection_id: String(conn.id),
          db_type: conn.db_type,
          host: conn.host,
          port: String(conn.port),
          database_name: conn.database_name,
          username: conn.username,
        },
        status: "connected",
        isFileUpload: false,
        tables: tables.map((t) => ({
          tableName: t.table_name,
          rows: 0,
          cols: 0,
          aiEnabled: true,
          state: "unselected" as const,
        })),
      };
      addSource(source);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not load tables for this connection",
      );
    } finally {
      setBusyId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-small text-ink-tertiary">
        <IconLoader2 size={15} className="animate-spin" /> Loading connected
        databases…
      </div>
    );
  }

  if (!connections || connections.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-secondary px-4 py-6 text-center text-small text-ink-tertiary">
        No connected databases yet. Create a connection on the{" "}
        <Link
          href="/database-connectors"
          className="font-medium text-brand-700 hover:underline"
        >
          Database Connectors
        </Link>{" "}
        page to use it here.
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {connections.map((conn) => {
          const spec = connectorSpec(conn.db_type);
          const added = sources.some(
            (s) => s.connectionConfig.connection_id === String(conn.id),
          );
          return (
            <div
              key={conn.id}
              className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-3.5"
            >
              <div className="mb-3 flex items-center gap-2.5">
                <span
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold ${
                    spec?.chip ?? "bg-bg-secondary text-ink-secondary"
                  }`}
                >
                  {spec?.initials ?? conn.db_type.slice(0, 2).toUpperCase()}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[14px] font-semibold text-ink-primary">
                    {conn.name}
                  </div>
                  <div className="truncate text-caption text-ink-tertiary">
                    {connectorDisplayName(conn.db_type)} · {conn.host}
                  </div>
                </div>
              </div>
              <Button
                variant={added ? "secondary" : "brandSoft"}
                size="sm"
                className="mt-auto w-full"
                onClick={() => handleCreate(conn)}
                disabled={busyId === conn.id}
              >
                {busyId === conn.id ? (
                  <IconLoader2 size={14} className="animate-spin" />
                ) : (
                  <IconPlus size={14} />
                )}
                {added ? "Edit selection" : "Create Data Source"}
              </Button>
            </div>
          );
        })}
      </div>
      {error && (
        <p className="mt-2 text-caption text-danger">{error}</p>
      )}
    </div>
  );
}
