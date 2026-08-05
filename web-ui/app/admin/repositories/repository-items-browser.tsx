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



export const PAGE_SIZE = 25;

export function RepositoryItemsBrowser({ connection }: { connection: RepositoryConnection }) {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const itemsQuery = useQuery({
    queryKey: ["repository-items", connection.id, offset, search],
    queryFn: () =>
      listRepositoryItems(connection.id, { limit: PAGE_SIZE, offset, search }),
  });
  const totalPages = itemsQuery.data
    ? Math.max(1, Math.ceil(itemsQuery.data.total / PAGE_SIZE))
    : 1;
  const page = Math.floor(offset / PAGE_SIZE);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">Items</h3>
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
          placeholder="Search name or path…"
          className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
      </div>

      {itemsQuery.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {itemsQuery.data && itemsQuery.data.items.length === 0 && (
        <p className="text-sm text-slate-500">No items found.</p>
      )}

      {itemsQuery.data && itemsQuery.data.items.length > 0 && (
        <>
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Name
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Type
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Size
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Extraction
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {itemsQuery.data.items.map((item: RepositoryItem) => (
                <tr key={item.id}>
                  <td className="px-3 py-2 text-sm text-slate-900">{item.name}</td>
                  <td className="px-3 py-2 text-sm text-slate-600">{item.item_type}</td>
                  <td className="px-3 py-2 text-sm text-slate-600">
                    {item.size != null ? item.size.toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={item.extraction_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
            <span>
              {offset + 1}–
              {Math.min(offset + PAGE_SIZE, itemsQuery.data.total)} of{" "}
              {itemsQuery.data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                disabled={page === 0}
                className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() =>
                  setOffset((o) =>
                    Math.min((totalPages - 1) * PAGE_SIZE, o + PAGE_SIZE),
                  )
                }
                disabled={page >= totalPages - 1}
                className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}