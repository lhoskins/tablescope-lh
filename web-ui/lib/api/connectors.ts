"use client";

import { apiClient } from "@/lib/api-client";

// ── Installed connectors (the catalog of deployed connector types) ────

export type ConnectorKind = "database" | "saas";

export interface InstalledConnector {
  key: string;
  name: string;
  kind: ConnectorKind;
  status: string;
}

export async function listInstalledConnectors(): Promise<InstalledConnector[]> {
  const res = await apiClient.get<{ connectors: InstalledConnector[] }>(
    "/api/connectors/installed",
  );
  return res.connectors;
}

// ── Saved database connection profiles ───────────────────────────────

export interface DbConnection {
  id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  has_password: boolean;
  ssl_mode: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_tested_at: string | null;
}

export interface DbConnectionInput {
  name: string;
  db_type: string;
  host: string;
  port?: number;
  database_name: string;
  username: string;
  password?: string;
  ssl_mode?: string;
}

export function listDbConnections(): Promise<DbConnection[]> {
  return apiClient.get<DbConnection[]>("/api/database-sources/connections");
}

export function createDbConnection(body: DbConnectionInput): Promise<DbConnection> {
  return apiClient.post<DbConnection>("/api/database-sources/connections", body);
}

export function updateDbConnection(
  id: number,
  body: Partial<DbConnectionInput>,
): Promise<DbConnection> {
  return apiClient.patch<DbConnection>(
    `/api/database-sources/connections/${id}`,
    body,
  );
}

export function testDbConnection(
  id: number,
): Promise<{ success: boolean; message: string }> {
  return apiClient.post(`/api/database-sources/connections/${id}/test`, {});
}

export function deleteDbConnection(id: number): Promise<{ status: string }> {
  return apiClient.delete(`/api/database-sources/connections/${id}`);
}

export function testDbConnectionInline(body: {
  db_type: string;
  host: string;
  port?: number;
  database_name: string;
  username: string;
  password?: string;
  ssl_mode?: string;
}): Promise<{ success: boolean; message: string }> {
  return apiClient.post("/api/database-sources/test", body);
}

// ── SaaS connector credentials ───────────────────────────────────────

export interface SaasCredential {
  id: number;
  connector_type: string;
  display_name: string;
  has_secret: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_tested_at: string | null;
}

export function listSaasCredentials(): Promise<SaasCredential[]> {
  return apiClient.get<SaasCredential[]>("/api/saas-sources/credentials");
}

export function createSaasCredential(body: {
  connector_type: string;
  display_name: string;
  config: Record<string, string>;
}): Promise<SaasCredential> {
  return apiClient.post<SaasCredential>("/api/saas-sources/credentials", body);
}

export function updateSaasCredential(
  id: number,
  body: { display_name?: string; config?: Record<string, string> },
): Promise<SaasCredential> {
  return apiClient.patch<SaasCredential>(
    `/api/saas-sources/credentials/${id}`,
    body,
  );
}

export function testSaasCredential(
  id: number,
): Promise<{ success: boolean; message: string }> {
  return apiClient.post("/api/saas-sources/test", { credential_id: id });
}

export function deleteSaasCredential(id: number): Promise<{ status: string }> {
  return apiClient.delete(`/api/saas-sources/credentials/${id}`);
}

export function testSaasInline(body: {
  connector_type: string;
  config: Record<string, string>;
}): Promise<{ success: boolean; message: string }> {
  return apiClient.post("/api/saas-sources/test", body);
}

// ── Unified "created connections" view (DB + SaaS merged) ─────────────

export interface CreatedConnection {
  kind: ConnectorKind;
  id: number;
  friendlyName: string;
  connectorKey: string;
  connectorName: string;
  hostOrAccount: string;
  lastTested: string | null;
}

const CONNECTOR_NAMES: Record<string, string> = {
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  sqlserver: "SQL Server",
  oracle: "Oracle",
  salesforce: "Salesforce",
  hubspot: "HubSpot",
  quickbooks: "QuickBooks",
};

export function connectorDisplayName(key: string): string {
  return CONNECTOR_NAMES[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

export async function listCreatedConnections(): Promise<CreatedConnection[]> {
  const [dbs, saas] = await Promise.all([
    listDbConnections().catch(() => [] as DbConnection[]),
    listSaasCredentials().catch(() => [] as SaasCredential[]),
  ]);

  const dbRows: CreatedConnection[] = dbs.map((c) => ({
    kind: "database",
    id: c.id,
    friendlyName: c.name,
    connectorKey: c.db_type,
    connectorName: connectorDisplayName(c.db_type),
    hostOrAccount: c.host,
    lastTested: c.last_tested_at ?? c.created_at,
  }));

  const saasRows: CreatedConnection[] = saas.map((c) => ({
    kind: "saas",
    id: c.id,
    friendlyName: c.display_name,
    connectorKey: c.connector_type,
    connectorName: connectorDisplayName(c.connector_type),
    hostOrAccount: connectorDisplayName(c.connector_type),
    lastTested: c.last_tested_at ?? c.created_at,
  }));

  return [...dbRows, ...saasRows];
}
