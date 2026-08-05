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
} from "@/lib/api/repository-connectors";import { StatusBadge } from "./status-badge";



export function ScanHistory({ connection }: { connection: RepositoryConnection }) {
  const scansQuery = useQuery({
    queryKey: ["repository-scans", connection.id],
    queryFn: () => listRepositoryScans(connection.id),
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <h3 className="text-base font-semibold text-slate-900">Scan history</h3>
      {scansQuery.isLoading && <p className="mt-2 text-sm text-slate-500">Loading…</p>}
      {scansQuery.data && scansQuery.data.length === 0 && (
        <p className="mt-2 text-sm text-slate-500">No scans yet.</p>
      )}
      {scansQuery.data && scansQuery.data.length > 0 && (
        <table className="mt-3 min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Status
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Files
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Directories
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Added
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Changed
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Deleted
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Completed
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {scansQuery.data.map((scan) => (
              <tr key={scan.id}>
                <td className="px-3 py-2">
                  <StatusBadge status={scan.status} />
                </td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.files_seen}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.directories_seen}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.added_count}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.changed_count}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.deleted_count}</td>
                <td className="px-3 py-2 text-sm text-slate-500">
                  {scan.completed_at ? new Date(scan.completed_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}