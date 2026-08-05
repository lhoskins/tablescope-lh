"use client";



import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRepositoryConnection,
  deleteRepositoryConnection,
  getRepositoryProfile,
  listRepositoryConnections,
  listRepositoryItems,
  listRepositoryScans,
  listRepositoryConnectorTypes,
  startRepositoryScan,
  testExistingRepositoryConnection,
  testRepositoryConnectionConfig,
  updateRepositoryConnection,
  type RepositoryConnection,
  type RepositoryConnectionCreate,
  type RepositoryConnectionUpdate,
  type RepositoryItem,
  type RepositoryScan,
} from "@/lib/api/repository-connectors";import { RepositoryItemsBrowser } from "./repository-items-browser";
import { classNames } from "./utils";
import { StatusBadge } from "./status-badge";
import { ConnectionForm } from "./connection-form";
import { ConnectionDetail } from "./connection-detail";
import { ScanHistory } from "./scan-history";
import { RepositoryProfile } from "./repository-profile";




export default function RepositoriesPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const connectionsQuery = useQuery({
    queryKey: ["repository-connections"],
    queryFn: listRepositoryConnections,
  });
  const typesQuery = useQuery({
    queryKey: ["repository-connector-types"],
    queryFn: listRepositoryConnectorTypes,
  });

  const selected = useMemo(
    () => connectionsQuery.data?.find((c) => c.id === selectedId) ?? null,
    [connectionsQuery.data, selectedId],
  );

  const createMutation = useMutation({
    mutationFn: createRepositoryConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository-connections"] });
      setIsCreating(false);
    },
  });

  return (
    <section className="space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Repositories</h1>
          <p className="mt-1 text-sm text-slate-500">
            Securely connect to UNC/SMB shares, scan metadata, and prepare file
            content for extraction.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setSelectedId(null);
            setIsCreating(true);
          }}
          className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand/90"
        >
          Add repository
        </button>
      </header>

      {connectionsQuery.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {connectionsQuery.error && (
        <p className="text-sm text-red-600">
          {(connectionsQuery.error as Error).message}
        </p>
      )}

      {connectionsQuery.data && connectionsQuery.data.length === 0 && !isCreating && (
        <p className="text-sm text-slate-500">
          No repository connectors configured yet.
        </p>
      )}

      {connectionsQuery.data && connectionsQuery.data.length > 0 && !isCreating && (
        <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Last scan
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {connectionsQuery.data.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => {
                    setSelectedId(c.id);
                    setIsCreating(false);
                  }}
                  className={classNames(
                    "cursor-pointer hover:bg-slate-50",
                    selectedId === c.id && "bg-brand-50",
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">{c.name}</div>
                    <div className="text-xs text-slate-400">{c.description}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {c.connector_type}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {c.last_successful_scan_at
                      ? new Date(c.last_successful_scan_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(isCreating || selected) && (
        <ConnectionForm
          connection={selected}
          connectorTypes={typesQuery.data ?? []}
          onCancel={() => {
            setIsCreating(false);
            setSelectedId(null);
          }}
          onCreate={(body) => createMutation.mutate(body)}
          onUpdate={(id, body) => updateRepositoryConnection(id, body)}
        />
      )}

      {selected && !isCreating && (
        <>
          <ConnectionDetail connection={selected} />
          <ScanHistory connection={selected} />
          <RepositoryProfile connection={selected} />
          <RepositoryItemsBrowser connection={selected} />
        </>
      )}
    </section>
  );
}
