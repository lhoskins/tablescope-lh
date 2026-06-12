"use client";

import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { AIFileUploadWizard } from "@/components/upload/AIFileUploadWizard";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { apiClient } from "@/lib/api-client";

type ColumnType = { name: string; field: string; type: string };

type Datasource = {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
  id?: number | null;
  fileMetaId?: number | null;
  archived?: boolean;
  columnTypes?: ColumnType[];
};

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

type QueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
};

export default function UploadPage() {
  const queryClient = useQueryClient();
  const [selectedDatasource, setSelectedDatasource] =
    useState<Datasource | null>(null);
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [querying, setQuerying] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);

  const datasourcesQuery = useQuery<Datasource[]>({
    queryKey: ["datasources"],
    queryFn: () => apiClient.get<Datasource[]>("/api/upload/datasources"),
  });

  type DbSource = {
    id: number;
    display_name: string;
    teiid_view_name: string;
    source_type: string;
    db_type: string;
    connector_type?: string | null;
    archived: boolean;
  };
  const archivedQuery = useQuery<DbSource[]>({
    queryKey: ["datasources", "archived"],
    queryFn: () =>
      apiClient.get<DbSource[]>("/api/database-sources?include_archived=true"),
  });
  const archived = (archivedQuery.data ?? []).filter((d) => d.archived);

  // Archived file sources (separate from DB/SaaS archived sources above).
  const archivedFilesQuery = useQuery<Datasource[]>({
    queryKey: ["datasources", "archived-files"],
    queryFn: () =>
      apiClient.get<Datasource[]>("/api/upload/datasources?include_archived=true"),
  });
  const archivedFiles = (archivedFilesQuery.data ?? []).filter(
    (d) => d.id == null && d.archived,
  );

  // Unified archived list (files + databases + SaaS) so they live under one
  // category with the same Restore / Delete actions (item 3).
  type ArchivedItem = {
    key: string;
    label: string;
    kind: "file" | "db";
    viewName?: string;
    id?: number;
  };
  const archivedAll: ArchivedItem[] = [
    ...archivedFiles.map((f) => ({
      key: `file:${f.viewName}`,
      label: f.fileName,
      kind: "file" as const,
      viewName: f.viewName,
    })),
    ...archived.map((d) => ({
      key: `db:${d.id}`,
      label: d.display_name,
      kind: "db" as const,
      id: d.id,
    })),
  ];

  async function restoreArchived(item: ArchivedItem) {
    if (item.kind === "file" && item.viewName) {
      await setFileArchived(item.viewName, false);
    } else if (item.kind === "db" && item.id != null) {
      await setArchivedById(item.id, false);
    }
  }

  async function deleteArchived(item: ArchivedItem) {
    if (item.kind === "file" && item.viewName) {
      await deleteFile(item.viewName, item.label);
    } else if (item.kind === "db" && item.id != null) {
      await deleteById(item.id, item.label);
    }
  }

  const [actionError, setActionError] = useState<string | null>(null);

  async function setFileArchived(viewName: string, archivedFlag: boolean) {
    setActionError(null);
    try {
      await apiClient.patch(
        `/api/upload/datasources/${encodeURIComponent(viewName)}/archive?archived=${archivedFlag}`,
        {},
      );
      queryClient.invalidateQueries({ queryKey: ["datasources"] });
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  async function deleteFile(viewName: string, label: string) {
    if (!window.confirm(`Permanently delete "${label}"? This cannot be undone.`)) {
      return;
    }
    setActionError(null);
    try {
      await apiClient.delete(`/api/upload/datasources/${encodeURIComponent(viewName)}`);
      queryClient.invalidateQueries({ queryKey: ["datasources"] });
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  // ── Item 5: drag a file onto a datasource row to replace it ──────────
  const [dragOverView, setDragOverView] = useState<string | null>(null);
  const [replaceMsg, setReplaceMsg] = useState<string | null>(null);
  // Item 6: confirm before overwriting an existing datasource.
  const [pendingReplace, setPendingReplace] = useState<
    { ds: Datasource; file: File } | null
  >(null);

  function replaceFromDrop(ds: Datasource, files: FileList | null) {
    setDragOverView(null);
    if (!files || files.length === 0) return;
    setActionError(null);
    setReplaceMsg(null);
    setPendingReplace({ ds, file: files[0] });
  }

  async function confirmReplace() {
    if (!pendingReplace) return;
    const { ds, file } = pendingReplace;
    setPendingReplace(null);
    setActionError(null);
    setReplaceMsg(null);
    try {
      const res = await apiClient.upload<{ addedColumns?: string[] }>(
        `/api/upload/datasources/${encodeURIComponent(ds.viewName)}/replace`,
        file,
      );
      const added = res.addedColumns ?? [];
      setReplaceMsg(
        `Replaced "${ds.fileName}"${added.length ? ` (added column(s): ${added.join(", ")})` : ""}.`,
      );
      queryClient.invalidateQueries({ queryKey: ["datasources"] });
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  const handleUploaded = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["datasources"] });
  }, [queryClient]);

  async function archiveDatasource(ds: Datasource, archived: boolean) {
    if (ds.id == null) return;
    setActionError(null);
    try {
      await apiClient.patch(
        `/api/database-sources/${ds.id}/archive?archived=${archived}`,
        {},
      );
      queryClient.invalidateQueries({ queryKey: ["datasources"] });
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  async function setArchivedById(id: number, archived: boolean) {
    setActionError(null);
    try {
      await apiClient.patch(
        `/api/database-sources/${id}/archive?archived=${archived}`,
        {},
      );
      queryClient.invalidateQueries({ queryKey: ["datasources"] });
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  async function deleteById(id: number, label: string) {
    if (!window.confirm(`Permanently delete "${label}"? This cannot be undone.`)) {
      return;
    }
    setActionError(null);
    try {
      await apiClient.delete(`/api/database-sources/${id}`);
      queryClient.invalidateQueries({ queryKey: ["datasources"] });
    } catch (err) {
      setActionError((err as Error).message);
    }
  }

  async function handleDatasourceClick(ds: Datasource) {
    setSelectedDatasource(ds);
    setQueryResult(null);
    setQueryError(null);
    setQuerying(true);
    try {
      const result = await apiClient.post<QueryResult>(
        "/api/query/datasource",
        { tableName: ds.viewName, limit: 1000 }
      );
      setQueryResult(result);
    } catch (err) {
      setQueryError((err as Error).message);
    } finally {
      setQuerying(false);
    }
  }

  const [uploadMode, setUploadMode] = useState<"quick" | "ai">("ai");

  return (
    <section>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Upload Files</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload data files (CSV, Excel) to your personal Teiid folder. Files
          are stored in your private workspace and can be queried through your
          VDB.
        </p>
      </header>

      {/* Upload mode toggle */}
      <div className="mb-4 flex gap-2">
        <button
          onClick={() => setUploadMode("ai")}
          className={`rounded-md px-4 py-2 text-sm font-medium ${
            uploadMode === "ai"
              ? "bg-blue-600 text-white"
              : "border border-slate-300 text-slate-700 hover:bg-slate-50"
          }`}
        >
          AI-Assisted Upload
        </button>
        <button
          onClick={() => setUploadMode("quick")}
          className={`rounded-md px-4 py-2 text-sm font-medium ${
            uploadMode === "quick"
              ? "bg-blue-600 text-white"
              : "border border-slate-300 text-slate-700 hover:bg-slate-50"
          }`}
        >
          Quick Upload
        </button>
      </div>

      {uploadMode === "ai" ? (
        <AIFileUploadWizard
          onComplete={() => {
            queryClient.invalidateQueries({ queryKey: ["datasources"] });
          }}
        />
      ) : (
        <>
          <FileDropzone onUploaded={handleUploaded} />
          <div className="mt-4">
            <ConnectorsMenu
              onCreated={() =>
                queryClient.invalidateQueries({ queryKey: ["datasources"] })
              }
            />
          </div>
        </>
      )}

      {/* Datasources list */}
      <div className="mt-8">
        <h2 className="mb-1 text-lg font-semibold text-slate-900">
          Your Datasources
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          Tip: drag a file (same name, same columns) onto a file datasource to
          replace its data. New columns are added automatically.
        </p>
        {replaceMsg && (
          <p className="mb-2 text-sm text-green-600">{replaceMsg}</p>
        )}
        {datasourcesQuery.isLoading && (
          <p className="text-sm text-slate-500">Loading datasources...</p>
        )}
        {datasourcesQuery.error && (
          <p className="text-sm text-red-600">
            {(datasourcesQuery.error as Error).message}
          </p>
        )}
        {datasourcesQuery.data && datasourcesQuery.data.length === 0 && (
          <p className="text-sm text-slate-400">
            No datasources yet. Upload a file above.
          </p>
        )}
        {actionError && (
          <p className="mb-2 text-sm text-red-600">{actionError}</p>
        )}
        {datasourcesQuery.data && datasourcesQuery.data.length > 0 && (
          <div className="grid gap-2">
            {datasourcesQuery.data.map((ds) => (
              <div
                key={ds.viewName}
                onDragOver={
                  ds.id == null
                    ? (e) => {
                        e.preventDefault();
                        setDragOverView(ds.viewName);
                      }
                    : undefined
                }
                onDragLeave={
                  ds.id == null ? () => setDragOverView(null) : undefined
                }
                onDrop={
                  ds.id == null
                    ? (e) => {
                        e.preventDefault();
                        replaceFromDrop(ds, e.dataTransfer.files);
                      }
                    : undefined
                }
                title={
                  ds.id == null
                    ? "Drop a file with the same name here to replace this datasource"
                    : undefined
                }
                className={`flex items-center justify-between rounded-md border px-4 py-3 transition-colors ${
                  dragOverView === ds.viewName
                    ? "border-brand border-dashed bg-brand/10 ring-2 ring-brand/30"
                    : selectedDatasource?.viewName === ds.viewName
                    ? "border-brand bg-brand/5"
                    : "border-slate-200 bg-white hover:bg-slate-50"
                }`}
              >
                <button
                  onClick={() => handleDatasourceClick(ds)}
                  className="flex-1 text-left"
                >
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-slate-900">
                      {ds.fileName}
                    </p>
                    <SourceBadge ds={ds} />
                  </div>
                  <p className="text-xs text-slate-400 font-mono">
                    View: {ds.viewName}
                  </p>
                </button>
                <div className="ml-3 flex items-center gap-3">
                  {typeof ds.size === "number" && (
                    <span className="text-xs text-slate-400">
                      {(ds.size / 1024).toFixed(1)} KB
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      ds.id != null
                        ? archiveDatasource(ds, true)
                        : setFileArchived(ds.viewName, true)
                    }
                    className="text-xs font-medium text-slate-500 hover:text-slate-800"
                    title="Archive (hide from list; delete becomes available once archived)"
                  >
                    Archive
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {archivedAll.length > 0 && (
          <details className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-600">
              Archived ({archivedAll.length})
            </summary>
            <p className="mt-1 mb-2 text-xs text-slate-400">
              Files, databases and SaaS sources archive here. Delete is only
              available after archiving and is blocked while a saved query
              depends on the source.
            </p>
            <div className="mt-2 grid gap-2">
              {archivedAll.map((item) => (
                <div
                  key={item.key}
                  className="flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2"
                >
                  <span className="text-sm text-slate-600">{item.label}</span>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => restoreArchived(item)}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800"
                    >
                      Restore
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteArchived(item)}
                      className="text-xs font-medium text-red-500 hover:text-red-700"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      {/* Data preview */}
      {selectedDatasource && (
        <div className="mt-6">
          <h3 className="mb-3 text-md font-semibold text-slate-900">
            Data: {selectedDatasource.fileName}
          </h3>
          {querying && (
            <p className="text-sm text-slate-500">Querying data...</p>
          )}
          {queryError && (
            <p className="text-sm text-red-600">{queryError}</p>
          )}
          {queryResult && queryResult.rows.length === 0 && (
            <p className="text-sm text-slate-400">No data in this datasource.</p>
          )}
          {queryResult && queryResult.rows.length > 0 && (
            <DataGrid
              columns={queryResult.columns}
              rows={queryResult.rows}
              columnTypes={selectedDatasource.columnTypes}
            />
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
