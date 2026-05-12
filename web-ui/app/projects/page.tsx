"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type Project = {
  id: number;
  name: string;
  description: string | null;
  is_shared: boolean;
};

export default function ProjectsPage() {
  const { data, isLoading, error } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => apiClient.get<Project[]>("/api/projects"),
  });

  return (
    <section>
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
      </header>
      {isLoading && <p>Loading projects…</p>}
      {error && <p className="text-red-600">{(error as Error).message}</p>}
      {data && (
        <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
          {data.map((project) => (
            <li
              key={project.id}
              className="flex items-center justify-between px-4 py-3"
            >
              <div>
                <p className="font-medium text-slate-900">{project.name}</p>
                <p className="text-sm text-slate-500">
                  {project.description ?? "—"}
                </p>
              </div>
              {project.is_shared ? (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                  shared
                </span>
              ) : (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                  private
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
