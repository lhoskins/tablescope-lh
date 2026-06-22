"use client";

import { apiClient } from "@/lib/api-client";
import type {
  PendingChanges,
  SessionSource,
} from "@/lib/stores/data-source-builder-store";

// ── Connection / discovery types ─────────────────────────────────────

export interface ConnectionParams {
  connection_id?: number;
  db_type?: string;
  host?: string;
  port?: number;
  database_name?: string;
  schema_name?: string;
  username?: string;
  password?: string;
  ssl_mode?: string;
}

export interface TestConnectionResult {
  success: boolean;
  message: string;
}

export interface DiscoveredTable {
  schema_name: string | null;
  table_name: string;
  type: string;
}

export interface SavedConnection {
  id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  has_password: boolean;
  ssl_mode: string | null;
}

export interface CreatedDbSource {
  id: number;
  display_name: string;
  teiid_view_name: string;
}

// ── File preview types ───────────────────────────────────────────────

export interface FilePreviewField {
  field_name: string;
  detected_type?: string;
  sample_values?: unknown[];
}

export interface FilePreviewResult {
  upload_session_id: string;
  file: {
    file_name: string;
    file_type: string;
    file_size_bytes: number;
    row_count: number;
    column_count: number;
    sheet_name: string | null;
  };
  fields: FilePreviewField[];
}

// ── Project / existing-source types ──────────────────────────────────

export interface ProjectDataSourceRow {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType: string;
  dbType: string | null;
  id?: number;
  fileMetaId?: number | null;
  ownerId?: number;
  columnTypes?: { name: string; type: string }[];
  aiMetadata?: Record<string, unknown>;
  archived?: boolean;
}

// ── Discovery / connection calls ─────────────────────────────────────

export function testConnection(
  params: ConnectionParams,
): Promise<TestConnectionResult> {
  return apiClient.post<TestConnectionResult>(
    "/api/database-sources/test",
    params,
  );
}

export async function listDbTables(
  params: ConnectionParams,
): Promise<DiscoveredTable[]> {
  const res = await apiClient.post<{ tables: DiscoveredTable[] }>(
    "/api/database-sources/tables",
    params,
  );
  return res.tables;
}

export async function listDbSchemas(
  params: ConnectionParams,
): Promise<string[]> {
  const res = await apiClient.post<{ schemas: string[] }>(
    "/api/database-sources/schemas",
    params,
  );
  return res.schemas;
}

export interface TablePreviewResult {
  columns: string[];
  rows: unknown[][];
}

export function previewDbTable(
  body: ConnectionParams & {
    schema_name?: string;
    table_name: string;
    limit?: number;
  },
): Promise<TablePreviewResult> {
  return apiClient.post<TablePreviewResult>(
    "/api/database-sources/preview",
    body,
  );
}

export function listSavedConnections(): Promise<SavedConnection[]> {
  return apiClient.get<SavedConnection[]>(
    "/api/database-sources/connections",
  );
}

export function createDbSource(body: {
  display_name: string;
  table_name: string;
  schema_name?: string;
  project_id?: number;
  save_connection?: boolean;
  connection_name?: string;
} & ConnectionParams): Promise<CreatedDbSource> {
  return apiClient.post<CreatedDbSource>("/api/database-sources", body);
}

// ── File calls ───────────────────────────────────────────────────────

export function analyzeFile(
  file: File,
  projectId?: number,
): Promise<FilePreviewResult> {
  return apiClient.upload<FilePreviewResult>(
    "/api/data-sources/upload/analyze",
    file,
    projectId ? { project_id: projectId } : undefined,
  );
}

export function finalizeFile(body: {
  upload_session_id: string;
  project_id?: number;
  display_name?: string;
}): Promise<{ view_name?: string; data_source_id?: number }> {
  return apiClient.post("/api/data-sources/upload/finalize", body);
}

// ── Project assignment calls ─────────────────────────────────────────

export function listProjectDataSources(
  projectId: string,
): Promise<ProjectDataSourceRow[]> {
  return apiClient.get<ProjectDataSourceRow[]>(
    `/api/projects/${projectId}/datasources`,
  );
}

export function addDataSourcesToProject(
  projectId: string,
  items: Array<
    | { kind: "file"; viewName: string }
    | { kind: "db"; id: number }
  >,
): Promise<{ status: string; added: number }> {
  return apiClient.post(`/api/projects/${projectId}/datasources/add`, {
    items,
  });
}

export function removeDataSourceFromProject(
  projectId: string,
  body:
    | { kind: "file"; viewName: string }
    | { kind: "db"; id: number },
): Promise<{ status: string }> {
  return apiClient.post(`/api/projects/${projectId}/datasources/remove`, body);
}

// ── Apply orchestration ──────────────────────────────────────────────

export interface ApplyOpResult {
  label: string;
  kind: "add" | "remove";
  ok: boolean;
  error?: string;
}

export interface ApplyResult {
  results: ApplyOpResult[];
  succeeded: number;
  failed: number;
}

/**
 * Commit a pending change-set against the real platform-api.
 *
 * - DB sources: each (selected table × project) becomes a DatabaseDataSource
 *   record (display name disambiguated by project when assigned to several).
 * - File sources: finalized into the first target project, then associated
 *   with any additional projects via the add endpoint.
 * - Removals: clear the project association for the source.
 */
export async function applyChanges(
  pending: PendingChanges,
  options: { mode?: "all" | "remove-only" } = {},
): Promise<ApplyResult> {
  const results: ApplyOpResult[] = [];
  const mode = options.mode ?? "all";

  // Removals first (surface impact, free up associations).
  for (const removal of pending.removing) {
    const label = `Remove ${removal.source.name} from ${removal.projectName}`;
    try {
      if (removal.source.kind === "file" && removal.source.viewName) {
        await removeDataSourceFromProject(removal.projectId, {
          kind: "file",
          viewName: removal.source.viewName,
        });
      } else if (
        removal.source.kind === "db" &&
        removal.source.backendId != null
      ) {
        await removeDataSourceFromProject(removal.projectId, {
          kind: "db",
          id: removal.source.backendId,
        });
      }
      results.push({ label, kind: "remove", ok: true });
    } catch (err) {
      results.push({
        label,
        kind: "remove",
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  if (mode === "all") {
    // Track which file sources have already been finalized (creates the record).
    const finalizedFileViewName = new Map<string, string>();

    // How many projects each source is being added to (for name disambiguation).
    const projectCountBySource = new Map<string, number>();
    for (const add of pending.adding) {
      projectCountBySource.set(
        add.source.id,
        (projectCountBySource.get(add.source.id) ?? 0) + 1,
      );
    }

    for (const add of pending.adding) {
      if (add.source.isFileUpload) {
        await applyFileAddition(add.source, add.projectId, add.projectName, finalizedFileViewName, results);
      } else {
        await applyDbAddition(
          add.source,
          add.projectId,
          add.projectName,
          add.tableNames,
          (projectCountBySource.get(add.source.id) ?? 1) > 1,
          results,
        );
      }
    }
  }

  const succeeded = results.filter((r) => r.ok).length;
  const failed = results.length - succeeded;
  return { results, succeeded, failed };
}

async function applyFileAddition(
  source: SessionSource,
  projectId: string,
  projectName: string,
  finalized: Map<string, string>,
  results: ApplyOpResult[],
): Promise<void> {
  const label = `Add ${source.displayName} to ${projectName}`;
  try {
    const already = finalized.get(source.id);
    if (!already) {
      const sessionId = source.fileMetadata?.uploadSessionId;
      if (!sessionId) {
        throw new Error("Missing upload session — re-add the file.");
      }
      const res = await finalizeFile({
        upload_session_id: sessionId,
        project_id: Number(projectId),
        display_name: source.displayName,
      });
      finalized.set(source.id, res.view_name ?? source.viewName ?? source.displayName);
    } else {
      await addDataSourcesToProject(projectId, [
        { kind: "file", viewName: already },
      ]);
    }
    results.push({ label, kind: "add", ok: true });
  } catch (err) {
    results.push({
      label,
      kind: "add",
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

async function applyDbAddition(
  source: SessionSource,
  projectId: string,
  projectName: string,
  tableNames: string[],
  multiProject: boolean,
  results: ApplyOpResult[],
): Promise<void> {
  for (const tableName of tableNames) {
    const displayName = multiProject
      ? `${tableName} · ${projectName}`
      : tableName;
    const label = `Add ${tableName} to ${projectName}`;
    try {
      await createDbSource({
        ...source.connectionConfig,
        port: source.connectionConfig.port
          ? Number(source.connectionConfig.port)
          : undefined,
        display_name: displayName,
        table_name: tableName,
        schema_name: source.connectionConfig.schema_name || undefined,
        project_id: Number(projectId),
      });
      results.push({ label, kind: "add", ok: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // Treat "already exists" as a soft success (idempotent re-apply).
      if (/already exists/i.test(message)) {
        results.push({ label, kind: "add", ok: true });
      } else {
        results.push({ label, kind: "add", ok: false, error: message });
      }
    }
  }
}
