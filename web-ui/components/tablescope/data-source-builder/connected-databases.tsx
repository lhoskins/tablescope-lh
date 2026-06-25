"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { IconLoader2, IconPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  listConnectedSources,
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
import { BrandLogo, connectorChip } from "../database-connectors/brand-logo";
import { TableSelectModal } from "./table-select-modal";

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
  const { data: connectedSources } = useQuery({
    queryKey: ["builder", "connected-sources"],
    queryFn: listConnectedSources,
  });
  const assignedSources = (connectedSources ?? []).filter(
    (s) => s.source === "assigned",
  );
  const addSource = useBuilderStore((s) => s.addSource);
  const sources = useBuilderStore((s) => s.sources);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modalSourceId, setModalSourceId] = useState<string | null>(null);

  // Open the table-selection flow for any connection-backed source (a
  // user-owned saved connection or a datasource assigned by an Admin). Both
  // resolve to a saved DatabaseConnection whose tables can be listed by id.
  const openConnection = async (opts: {
    connectionId: number;
    displayName: string;
    dbType: string;
    host: string;
    database: string;
    port?: number | null;
    username?: string | null;
  }) => {
    // If this connection already has a session source, just open it.
    const existing = sources.find(
      (s) => s.connectionConfig.connection_id === String(opts.connectionId),
    );
    if (existing) {
      setModalSourceId(existing.id);
      return;
    }
    setBusyId(opts.connectionId);
    setError(null);
    try {
      const tables = await listDbTables({ connection_id: opts.connectionId });
      const connectionConfig: Record<string, string> = {
        connection_id: String(opts.connectionId),
        db_type: opts.dbType,
        host: opts.host,
        database_name: opts.database,
      };
      if (opts.port != null) connectionConfig.port = String(opts.port);
      if (opts.username) connectionConfig.username = opts.username;
      const source: SessionSource = {
        id: `conn-${opts.connectionId}-${Date.now()}`,
        sourceType: toSourceType(opts.dbType),
        displayName: opts.displayName,
        connectionConfig,
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
      setModalSourceId(source.id);
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

  const handleCreate = (conn: SavedConnection) =>
    openConnection({
      connectionId: conn.id,
      displayName: conn.name,
      dbType: conn.db_type,
      host: conn.host,
      database: conn.database_name,
      port: conn.port,
      username: conn.username,
    });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-small text-ink-tertiary">
        <IconLoader2 size={15} className="animate-spin" /> Loading connected
        databases…
      </div>
    );
  }

  const hasOwned = Boolean(connections && connections.length > 0);

  if (!hasOwned && assignedSources.length === 0) {
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
        {assignedSources.map((src) => {
          const connId = src.database_connection_id;
          const added =
            connId != null &&
            sources.some(
              (s) => s.connectionConfig.connection_id === String(connId),
            );
          return (
            <div
              key={src.id}
              className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-3.5"
            >
              <div className="mb-2 flex items-center gap-2.5">
                <span
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${connectorChip(
                    src.db_type,
                  )}`}
                >
                  <BrandLogo connector={src.db_type} size={20} />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[14px] font-semibold text-ink-primary">
                    {src.display_name}
                  </div>
                  <div className="truncate text-caption text-ink-tertiary">
                    {connectorDisplayName(src.db_type)}
                  </div>
                  <div className="truncate text-caption text-ink-tertiary">
                    {src.host}
                  </div>
                </div>
              </div>
              <div className="mb-3 flex flex-wrap gap-1.5">
                <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">
                  {src.assigned_by ? `Assigned by ${src.assigned_by}` : "Shared"}
                </span>
                {src.read_only && (
                  <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-[11px] font-medium text-ink-tertiary">
                    Read-only
                  </span>
                )}
              </div>
              {connId != null ? (
                <Button
                  variant={added ? "secondary" : "brandSoft"}
                  size="sm"
                  className="mt-auto w-full"
                  onClick={() =>
                    openConnection({
                      connectionId: connId,
                      displayName: src.display_name,
                      dbType: src.db_type,
                      host: src.host,
                      database: src.database,
                    })
                  }
                  disabled={busyId === connId}
                >
                  {busyId === connId ? (
                    <IconLoader2 size={14} className="animate-spin" />
                  ) : (
                    <IconPlus size={14} />
                  )}
                  {added ? "Edit selection" : "Create Data Source"}
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-auto w-full"
                  disabled
                  title="This shared source has no table picker available."
                >
                  Shared data source
                </Button>
              )}
            </div>
          );
        })}
        {(connections ?? []).map((conn) => {
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
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${connectorChip(
                    conn.db_type,
                  )}`}
                >
                  <BrandLogo connector={conn.db_type} size={20} />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[14px] font-semibold text-ink-primary">
                    {conn.name}
                  </div>
                  <div className="truncate text-caption text-ink-tertiary">
                    {connectorDisplayName(conn.db_type)}
                  </div>
                  <div className="truncate text-caption text-ink-tertiary">
                    {conn.host}
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
      {error && <p className="mt-2 text-caption text-danger">{error}</p>}
      {modalSourceId && (
        <TableSelectModal
          sourceId={modalSourceId}
          onClose={() => setModalSourceId(null)}
        />
      )}
    </div>
  );
}
