"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAssignment,
  deleteAssignment,
  listAssignableSources,
  listAssignableUsers,
  listAssignments,
} from "@/lib/api/data-source-assignments";

const SOURCES_KEY = ["assignable-db-sources"] as const;
const USERS_KEY = ["assignable-users"] as const;
const ASSIGNMENTS_KEY = ["data-source-assignments"] as const;

export default function DataSourceAssignmentsPage() {
  const queryClient = useQueryClient();
  const [sourceId, setSourceId] = useState<number | "">("");
  const [friendlyName, setFriendlyName] = useState("");
  const [readOnly, setReadOnly] = useState(true);
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);

  const sourcesQuery = useQuery({
    queryKey: SOURCES_KEY,
    queryFn: listAssignableSources,
  });
  const usersQuery = useQuery({
    queryKey: USERS_KEY,
    queryFn: listAssignableUsers,
  });
  const assignmentsQuery = useQuery({
    queryKey: ASSIGNMENTS_KEY,
    queryFn: listAssignments,
  });

  const sources = sourcesQuery.data ?? [];
  const users = usersQuery.data ?? [];
  const assignments = assignmentsQuery.data ?? [];

  const selectedSource = useMemo(
    () => sources.find((s) => s.database_data_source_id === sourceId),
    [sources, sourceId],
  );

  const createMutation = useMutation({
    mutationFn: createAssignment,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ASSIGNMENTS_KEY });
      setFriendlyName("");
      setSelectedUsers([]);
      setSourceId("");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: deleteAssignment,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ASSIGNMENTS_KEY }),
    onError: (err: Error) => setError(err.message),
  });

  function toggleUser(id: number) {
    setSelectedUsers((prev) =>
      prev.includes(id) ? prev.filter((u) => u !== id) : [...prev, id],
    );
  }

  function handleAssign(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (sourceId === "") {
      setError("Select a database datasource to assign.");
      return;
    }
    if (!friendlyName.trim()) {
      setError("Enter a friendly name users will see.");
      return;
    }
    if (selectedUsers.length === 0) {
      setError("Select at least one user.");
      return;
    }
    createMutation.mutate({
      database_data_source_id: sourceId,
      assigned_user_ids: selectedUsers,
      friendly_name: friendlyName.trim(),
      read_only: readOnly,
    });
  }

  return (
    <section className="max-w-4xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">
          Data Source Assignments
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Assign already-configured database datasources to users. Assigned
          datasources appear in each user&apos;s Data Source Builder under
          Connected Databases without exposing the underlying credentials.
        </p>
      </header>

      <div className="space-y-6">
        <form
          onSubmit={handleAssign}
          className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Datasource
            </label>
            <select
              value={sourceId}
              onChange={(e) =>
                setSourceId(e.target.value ? Number(e.target.value) : "")
              }
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            >
              <option value="">Select a datasource…</option>
              {sources.map((s) => (
                <option
                  key={s.database_data_source_id}
                  value={s.database_data_source_id}
                >
                  {s.display_name} ({s.db_type} · {s.database_name}.
                  {s.table_name})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Friendly name
            </label>
            <input
              type="text"
              value={friendlyName}
              onChange={(e) => setFriendlyName(e.target.value)}
              placeholder={
                selectedSource?.display_name ?? "Boeing Supplier Quality DB"
              }
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Assign to users
            </label>
            {usersQuery.isLoading ? (
              <p className="text-sm text-slate-500">Loading users…</p>
            ) : (
              <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-slate-200 p-2">
                {users.map((u) => (
                  <label
                    key={u.id}
                    className="flex items-center gap-2 rounded px-1 py-1 text-sm hover:bg-slate-50"
                  >
                    <input
                      type="checkbox"
                      checked={selectedUsers.includes(u.id)}
                      onChange={() => toggleUser(u.id)}
                    />
                    <span className="text-slate-800">
                      {u.display_name || u.email}
                    </span>
                    <span className="text-xs text-slate-400">{u.role}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={readOnly}
              onChange={(e) => setReadOnly(e.target.checked)}
            />
            Read-only
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={createMutation.isPending}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {createMutation.isPending ? "Assigning…" : "Assign datasource"}
          </button>
        </form>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-medium text-slate-900">
            Existing assignments
          </h2>
          {assignmentsQuery.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : assignments.length === 0 ? (
            <p className="text-sm text-slate-500">No assignments yet.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-400">
                <tr>
                  <th className="py-2">Friendly name</th>
                  <th className="py-2">Datasource</th>
                  <th className="py-2">Assigned to</th>
                  <th className="py-2">Assigned by</th>
                  <th className="py-2">Status</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {assignments.map((a) => (
                  <tr key={a.id}>
                    <td className="py-2 text-slate-800">{a.friendly_name}</td>
                    <td className="py-2 text-slate-600">
                      {a.datasource_name ?? a.database_data_source_id}
                    </td>
                    <td className="py-2 text-slate-600">
                      {a.assigned_user_name || a.assigned_user_email}
                    </td>
                    <td className="py-2 text-slate-600">
                      {a.assigned_by_name ?? "—"}
                    </td>
                    <td className="py-2">
                      <span
                        className={
                          a.is_active
                            ? "text-emerald-600"
                            : "text-slate-400"
                        }
                      >
                        {a.is_active ? "Active" : "Inactive"}
                        {a.read_only ? " · read-only" : ""}
                      </span>
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => removeMutation.mutate(a.id)}
                        disabled={removeMutation.isPending}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
}
