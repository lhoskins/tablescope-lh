"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { listDbTables, type DiscoveredTable } from "@/lib/api/data-source-builder";
import type { ConnectedSource } from "@/lib/api/data-source-catalog";
import type { CreatedConnection } from "@/lib/api/connectors";
import type { NetworkFileConnection } from "@/lib/api/network-file-connections";
import type { SaasCredential } from "@/lib/api/connectors";
import {
  useBuilderStore,
  type SessionSource,
  type SourceType,
  type TableSelection,
} from "@/lib/stores/data-source-builder-store";

const DB_SOURCE_TYPES = new Set<SourceType>([
  "postgresql",
  "mysql",
  "snowflake",
  "bigquery",
]);

function toSourceType(dbType: string): SourceType {
  return DB_SOURCE_TYPES.has(dbType as SourceType)
    ? (dbType as SourceType)
    : "postgresql";
}

function tablesToSelections(tables: DiscoveredTable[]): TableSelection[] {
  return tables.map((t) => ({
    tableName: t.table_name,
    schemaName: t.schema_name,
    rows: 0,
    cols: 0,
    aiEnabled: true,
    state: "unselected" as const,
  }));
}

export function useConnectedSourceActions() {
  const queryClient = useQueryClient();
  const addSource = useBuilderStore((s) => s.addSource);
  const sources = useBuilderStore((s) => s.sources);

  const [activeDbSourceId, setActiveDbSourceId] = useState<string | null>(null);
  const [activeSaasCredential, setActiveSaasCredential] = useState<SaasCredential | null>(null);
  const [activeNetworkConnection, setActiveNetworkConnection] = useState<NetworkFileConnection | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const invalidateConnectedSources = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["builder", "connected-sources"] });
  }, [queryClient]);

  const createDbSessionSource = useCallback(
    async (opts: {
      connectionId: number;
      displayName: string;
      dbType: string;
      host: string;
      database?: string | null;
      port?: number | null;
      username?: string | null;
    }) => {
      const existing = sources.find(
        (s) => s.connectionConfig.connection_id === String(opts.connectionId),
      );
      if (existing) {
        setActiveDbSourceId(existing.id);
        return;
      }

      setBusyId(`db-${opts.connectionId}`);
      setError(null);
      try {
        const tables = await listDbTables({ connection_id: opts.connectionId });
        const connectionConfig: Record<string, string> = {
          connection_id: String(opts.connectionId),
          db_type: opts.dbType,
          host: opts.host,
          database_name: opts.database ?? "",
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
          tables: tablesToSelections(tables),
        };
        addSource(source);
        setActiveDbSourceId(source.id);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Could not load tables for this connection",
        );
      } finally {
        setBusyId(null);
      }
    },
    [addSource, sources],
  );

  const openDbFromConnectedSource = useCallback(
    (src: ConnectedSource) => {
      if (!src.connectionId) return;
      void createDbSessionSource({
        connectionId: src.connectionId,
        displayName: src.friendlyName,
        dbType: src.connectorType,
        host: src.displayLocation,
        database: src.databaseName,
        port: src.port,
      });
    },
    [createDbSessionSource],
  );

  const openDbFromCreatedConnection = useCallback(
    (conn: CreatedConnection) => {
      void createDbSessionSource({
        connectionId: conn.id,
        displayName: conn.friendlyName,
        dbType: conn.connectorKey,
        host: conn.hostOrAccount,
        database: conn.databaseName,
        port: conn.port,
        username: conn.username,
      });
    },
    [createDbSessionSource],
  );

  const openSaasFromConnectedSource = useCallback((src: ConnectedSource) => {
    if (!src.credentialId) return;
    const credential: SaasCredential = {
      id: src.credentialId,
      connector_type: src.connectorType,
      display_name: src.friendlyName,
      has_secret: true,
      created_at: null,
      updated_at: null,
      last_tested_at: null,
    };
    setActiveSaasCredential(credential);
  }, []);

  const openSaasFromCreatedConnection = useCallback((conn: CreatedConnection) => {
    const credential: SaasCredential = {
      id: conn.id,
      connector_type: conn.connectorKey,
      display_name: conn.friendlyName,
      has_secret: true,
      created_at: null,
      updated_at: null,
      last_tested_at: null,
    };
    setActiveSaasCredential(credential);
  }, []);

  const openNetworkFromConnectedSource = useCallback((src: ConnectedSource) => {
    if (!src.connectionId) return;
    const connection = {
      id: src.connectionId,
      name: src.friendlyName,
      label: src.displayLocation,
    } as unknown as NetworkFileConnection;
    setActiveNetworkConnection(connection);
  }, []);

  const closeDbModal = useCallback(() => setActiveDbSourceId(null), []);
  const closeSaasModal = useCallback(() => setActiveSaasCredential(null), []);
  const closeNetworkModal = useCallback(() => setActiveNetworkConnection(null), []);

  return {
    busyId,
    error,
    activeDbSourceId,
    activeSaasCredential,
    activeNetworkConnection,
    openDbFromConnectedSource,
    openDbFromCreatedConnection,
    openSaasFromConnectedSource,
    openSaasFromCreatedConnection,
    openNetworkFromConnectedSource,
    closeDbModal,
    closeSaasModal,
    closeNetworkModal,
    invalidateConnectedSources,
  };
}
