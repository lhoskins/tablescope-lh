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

  const handleUploaded = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["datasources"] });
  }, [queryClient]);

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
        {datasourcesQuery.data && datasourcesQuery.data.length > 0 && (
          <div className="grid gap-2">
            {datasourcesQuery.data.map((ds) => (
              <button
                key={ds.viewName}
                onClick={() => handleDatasourceClick(ds)}
                className={`flex items-center justify-between rounded-md border px-4 py-3 text-left transition-colors hover:bg-slate-50 ${
                  selectedDatasource?.viewName === ds.viewName
                    ? "border-brand bg-brand/5"
                    : "border-slate-200 bg-white"
                }`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-slate-900">
                      {ds.fileName}
                    </p>
                    <SourceBadge ds={ds} />
                  </div>
                  <p className="text-xs text-slate-400 font-mono">
                    View: {ds.viewName}
                  </p>
                </div>
                {typeof ds.size === "number" && (
                  <span className="text-xs text-slate-400">
                    {(ds.size / 1024).toFixed(1)} KB
                  </span>
                )}
              </button>
            ))}
          </div>
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
