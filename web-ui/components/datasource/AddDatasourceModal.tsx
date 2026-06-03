"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type AvailableDatasource = {
  kind: "file" | "db";
  id?: number;
  fileName: string;
  viewName: string;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
};

function badge(ds: AvailableDatasource): { label: string; cls: string } {
  if (ds.sourceType === "saas_object") {
    const c = (ds.connectorType ?? "saas").toLowerCase();
    const label =
      c === "hubspot"
        ? "HubSpot"
        : c === "salesforce"
        ? "Salesforce"
        : c === "quickbooks"
        ? "QuickBooks"
        : "SaaS";
    return { label, cls: "bg-sky-100 text-sky-700" };
  }
  if (ds.sourceType === "database_table") {
    const db = (ds.dbType ?? "database").toLowerCase();
    const label =
      db === "postgresql"
        ? "PostgreSQL"
        : db === "mysql"
        ? "MySQL"
        : db === "sqlserver"
        ? "SQL Server"
        : db === "oracle"
        ? "Oracle"
        : "Database";
    return { label, cls: "bg-indigo-100 text-indigo-700" };
  }
  return { label: (ds.sourceType ?? "file").toUpperCase(), cls: "bg-emerald-100 text-emerald-700" };
}

function keyFor(ds: AvailableDatasource): string {
  return ds.kind === "db" ? `db:${ds.id}` : `file:${ds.viewName}`;
}

export function AddDatasourceModal({
  projectId,
  onClose,
  onAdded,
}: {
  projectId: number;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [selected, setSelected] = useState<Record<string, AvailableDatasource>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const availableQuery = useQuery<AvailableDatasource[]>({
    queryKey: ["available-datasources", projectId],
    queryFn: () =>
      apiClient.get<AvailableDatasource[]>(
        `/api/projects/${projectId}/available-datasources`,
      ),
  });

  const items = availableQuery.data ?? [];
  const selectedCount = Object.keys(selected).length;

  function toggle(ds: AvailableDatasource) {
    setSelected((prev) => {
      const k = keyFor(ds);
      const next = { ...prev };
      if (next[k]) {
        delete next[k];
      } else {
        next[k] = ds;
      }
      return next;
    });
  }

  async function handleAdd() {
    if (selectedCount === 0) return;
    setBusy(true);
    setError(null);
    try {
      const payload = Object.values(selected).map((ds) =>
        ds.kind === "db"
          ? { kind: "db", id: ds.id }
          : { kind: "file", viewName: ds.viewName },
      );
      await apiClient.post(`/api/projects/${projectId}/datasources/add`, {
        items: payload,
      });
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add datasources");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-xl max-h-[85vh] overflow-hidden rounded-lg bg-white p-6 shadow-xl flex flex-col">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Add Datasource</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <p className="mb-3 text-sm text-slate-500">
          Select existing datasources to add to this project.
        </p>

        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto rounded-md border border-slate-200">
          {availableQuery.isLoading && (
            <p className="px-3 py-3 text-sm text-slate-400">Loading...</p>
          )}
          {!availableQuery.isLoading && items.length === 0 && (
            <p className="px-3 py-3 text-sm text-slate-400">
              No other datasources available to add. Create one from the
              Connectors menu or upload a file from your personal workspace.
            </p>
          )}
          {items.map((ds) => {
            const b = badge(ds);
            const k = keyFor(ds);
            const isSelected = !!selected[k];
            return (
              <button
                key={k}
                type="button"
                onClick={() => toggle(ds)}
                className={`flex w-full items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-left text-sm transition-colors ${
                  isSelected ? "bg-brand/10" : "hover:bg-slate-50"
                }`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    readOnly
                    checked={isSelected}
                    className="h-4 w-4 rounded border-slate-300 text-brand"
                  />
                  <span className="font-medium text-slate-800">{ds.fileName}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${b.cls}`}>
                    {b.label}
                  </span>
                </span>
                <span className="font-mono text-xs text-slate-400">{ds.viewName}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-4 flex justify-between">
          <button
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={handleAdd}
            disabled={busy || selectedCount === 0}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {busy ? "Adding..." : `Add${selectedCount ? ` (${selectedCount})` : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
