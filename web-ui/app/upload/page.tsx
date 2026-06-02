"use client";

import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";
import { apiClient } from "@/lib/api-client";

type Datasource = {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
  id?: number | null;
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

  const [actionError, setActionError] = useState<string | null>(null);

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

  async function deleteDatasource(ds: Datasource) {
    if (ds.id == null) return;
    await deleteById(ds.id, ds.fileName);
    if (selectedDatasource?.viewName === ds.viewName) setSelectedDatasource(null);
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

      <FileDropzone onUploaded={handleUploaded} />

      <div className="mt-4">
        <ConnectorsMenu
          onCreated={() =>
            queryClient.invalidateQueries({ queryKey: ["datasources"] })
          }
        />
      </div>

      {/* Datasources list */}
      <div className="mt-8">
        <h2 className="mb-3 text-lg font-semibold text-slate-900">
          Your Datasources
        </h2>
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
                className={`flex items-center justify-between rounded-md border px-4 py-3 transition-colors ${
                  selectedDatasource?.viewName === ds.viewName
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
                  {ds.id != null && (
                    <>
                      <button
                        type="button"
                        onClick={() => archiveDatasource(ds, true)}
                        className="text-xs font-medium text-slate-500 hover:text-slate-800"
                        title="Archive (hide from list; can be deleted later)"
                      >
                        Archive
                      </button>
                      <button
                        type="button"
                        onClick={() => deleteDatasource(ds)}
                        className="text-xs font-medium text-red-500 hover:text-red-700"
                        title="Delete (archive first; blocked if a query depends on it)"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {archived.length > 0 && (
          <details className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-600">
              Archived ({archived.length})
            </summary>
            <div className="mt-2 grid gap-2">
              {archived.map((d) => (
                <div
                  key={d.id}
                  className="flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2"
                >
                  <span className="text-sm text-slate-600">{d.display_name}</span>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setArchivedById(d.id, false)}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800"
                    >
                      Restore
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteById(d.id, d.display_name)}
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
            <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    {queryResult.columns.map((col) => (
                      <th
                        key={col}
                        className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {queryResult.rows.slice(0, 100).map((row, i) => (
                    <tr key={i}>
                      {queryResult.columns.map((col) => (
                        <td
                          key={col}
                          className="whitespace-nowrap px-3 py-2 text-sm text-slate-700"
                        >
                          {String(row[col] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {queryResult.rows.length > 100 && (
                <p className="px-3 py-2 text-xs text-slate-400">
                  Showing first 100 of {queryResult.rows.length} rows
                </p>
              )}
            </div>
          )}
        </div>
      )}

    </section>
  );
}
