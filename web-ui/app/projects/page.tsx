"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type Project = {
  id: number;
  name: string;
  description: string | null;
  type: string | null;
  is_shared: boolean;
  owner_id: number | null;
  created_at: string;
};

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isShared, setIsShared] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading, error: fetchError } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => apiClient.get<Project[]>("/api/projects"),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { name: string; description: string; is_shared: boolean }) =>
      apiClient.post<Project>("/api/projects", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowCreate(false);
      setName("");
      setDescription("");
      setIsShared(false);
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/api/projects/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    createMutation.mutate({ name, description, is_shared: isShared });
  }

  return (
    <section>
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
        >
          {showCreate ? "Cancel" : "Create Project"}
        </button>
      </header>

      {showCreate && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
        >
          <h2 className="mb-4 text-lg font-medium text-slate-900">
            New Project
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Project Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="My Project"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="Optional description"
              />
            </div>
            <div className="flex items-center gap-3">
              <label className="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  checked={isShared}
                  onChange={(e) => setIsShared(e.target.checked)}
                  className="peer sr-only"
                />
                <div className="h-5 w-9 rounded-full bg-slate-200 after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-brand peer-checked:after:translate-x-full" />
              </label>
              <span className="text-sm text-slate-700">
                {isShared ? "Shared project" : "Private project"}
              </span>
            </div>
            <p className="text-xs text-slate-500">
              {isShared
                ? "Shared projects use the tenant-wide SharedVDB. All tenant members with access can query the data."
                : "Private projects route queries to your personal UserVDB. Only you can access the data until you share it."}
            </p>
            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
            <button
              type="submit"
              disabled={createMutation.isPending || !name.trim()}
              className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      )}

      {isLoading && <p>Loading projects...</p>}
      {fetchError && (
        <p className="text-red-600">{(fetchError as Error).message}</p>
      )}
      {data && data.length === 0 && !showCreate && (
        <div className="rounded-lg border-2 border-dashed border-slate-200 p-12 text-center">
          <p className="text-slate-500">No projects yet.</p>
          <p className="mt-1 text-sm text-slate-400">
            Click &quot;Create Project&quot; to get started.
          </p>
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
          {data.map((project) => (
            <li
              key={project.id}
              className="flex items-center justify-between px-4 py-3"
            >
              <div>
                <p className="font-medium text-slate-900">{project.name}</p>
                <p className="text-sm text-slate-500">
                  {project.description ?? "No description"}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {project.is_shared ? (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                    shared
                  </span>
                ) : (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    private
                  </span>
                )}
                <button
                  onClick={() => {
                    if (confirm("Delete this project?")) {
                      deleteMutation.mutate(project.id);
                    }
                  }}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
