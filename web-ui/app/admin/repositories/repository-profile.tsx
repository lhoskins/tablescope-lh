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
} from "@/lib/api/repository-connectors";


export function RepositoryProfile({ connection }: { connection: RepositoryConnection }) {
  const profileQuery = useQuery({
    queryKey: ["repository-profile", connection.id],
    queryFn: () => getRepositoryProfile(connection.id),
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <h3 className="text-base font-semibold text-slate-900">Profile</h3>
      {profileQuery.isLoading && <p className="mt-2 text-sm text-slate-500">Loading…</p>}
      {profileQuery.data && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Total files"
            value={Number(profileQuery.data.profile.total_files ?? 0)}
          />
          <StatCard
            label="Directories"
            value={Number(profileQuery.data.profile.total_directories ?? 0)}
          />
          <StatCard
            label="Total bytes"
            value={Number(profileQuery.data.profile.total_bytes ?? 0)}
          />
          <StatCard
            label="Duplicate candidates"
            value={Number(profileQuery.data.profile.duplicate_candidates ?? 0)}
          />
        </div>
      )}
    </div>
  );
}

export function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-2xl font-semibold text-slate-900">{value.toLocaleString()}</div>
      <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}