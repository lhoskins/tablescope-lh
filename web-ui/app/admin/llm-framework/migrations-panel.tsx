"use client";


import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  activateLLMDeployment,
  approveLLMDeployment,
  getLLMAuditEvents,
  getLLMCapabilities,
  getLLMDeployments,
  getLLMFrameworkStatus,
  getLLMInventory,
  getLLMEmbeddingMigrations,
  getLLMModelConversions,
  installLLMArtifact,
  preflightLLMInstall,
  registerLLMRuntimeTarget,
  rollbackLLMDeployment,
  searchLLMCatalog,
  stageLLMArtifact,
  reindexLLMArtifact,
  convertLLMCatalogEntry,
  upsertLLMRoutingProfile,
  type AuditEvent,
  type CatalogSearchResult,
  type Deployment,
  type LLMInventory,
  type RuntimeTarget,
} from "@/lib/api/llm-framework";import { formatDate, Section, StatusBadge } from "./utils";



export function MigrationsPanel() {
  const [artifactId, setArtifactId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("nomic-embed-text");
  const [embeddingDim, setEmbeddingDim] = useState("768");

  const statusQuery = useQuery({
    queryKey: ["llm-framework", "status"],
    queryFn: getLLMFrameworkStatus,
  });
  const query = useQuery({
    queryKey: ["llm-framework", "embedding-migrations"],
    queryFn: getLLMEmbeddingMigrations,
    refetchInterval: 5000,
  });
  const mutation = useMutation({
    mutationFn: (payload: { artifact_id: number; tenant_id: number; embedding_model: string; embedding_dim: number }) =>
      reindexLLMArtifact(payload.artifact_id, {
        tenant_id: payload.tenant_id,
        embedding_model: payload.embedding_model,
        embedding_dim: payload.embedding_dim,
      }),
    onSuccess: () => query.refetch(),
  });

  const isEnabled = statusQuery.data?.embedding_migration_enabled ?? false;

  return (
    <div className="space-y-4">
      <Section title="Start embedding re-index">
        <div className="grid gap-3 sm:grid-cols-5">
          <input
            type="number"
            placeholder="Artifact ID"
            className="rounded-md border border-line-tertiary px-3 py-2 text-sm"
            value={artifactId}
            onChange={(e) => setArtifactId(e.target.value)}
          />
          <input
            type="number"
            placeholder="Tenant ID"
            className="rounded-md border border-line-tertiary px-3 py-2 text-sm"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          />
          <input
            type="text"
            placeholder="Embedding model"
            className="rounded-md border border-line-tertiary px-3 py-2 text-sm"
            value={embeddingModel}
            onChange={(e) => setEmbeddingModel(e.target.value)}
          />
          <input
            type="number"
            placeholder="Embedding dim"
            className="rounded-md border border-line-tertiary px-3 py-2 text-sm"
            value={embeddingDim}
            onChange={(e) => setEmbeddingDim(e.target.value)}
          />
          <button
            onClick={() =>
              mutation.mutate({
                artifact_id: Number(artifactId),
                tenant_id: Number(tenantId),
                embedding_model: embeddingModel,
                embedding_dim: Number(embeddingDim),
              })
            }
            disabled={!artifactId || !tenantId || mutation.isPending}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Starting..." : "Re-index"}
          </button>
        </div>
        {mutation.isError && <p className="text-sm text-red-600">{(mutation.error as Error)?.message ?? "Failed to start"}</p>}
        {mutation.isSuccess && <p className="text-sm text-emerald-600">Migration {mutation.data.migration_id} queued.</p>}
        {!isEnabled && <p className="text-sm text-ink-tertiary">Embedding migration is disabled in configuration.</p>}
      </Section>

      <Section title="Embedding migrations">
        {query.isLoading ? (
          <p className="text-sm text-ink-tertiary">Loading...</p>
        ) : query.data?.length === 0 ? (
          <p className="text-sm text-ink-tertiary">No embedding migrations yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line-tertiary text-ink-tertiary">
                <tr>
                  <th className="py-2 pr-4 font-medium">ID</th>
                  <th className="py-2 pr-4 font-medium">Tenant</th>
                  <th className="py-2 pr-4 font-medium">Artifact</th>
                  <th className="py-2 pr-4 font-medium">Model</th>
                  <th className="py-2 pr-4 font-medium">Dim</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Indexed</th>
                  <th className="py-2 pr-4 font-medium">Recall</th>
                  <th className="py-2 pr-4 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-tertiary text-ink-secondary">
                {query.data?.map((m) => (
                  <tr key={m.id}>
                    <td className="py-2 pr-4">{m.id}</td>
                    <td className="py-2 pr-4">{m.tenant_id}</td>
                    <td className="py-2 pr-4">{m.artifact_id}</td>
                    <td className="py-2 pr-4">{m.embedding_model}</td>
                    <td className="py-2 pr-4">{m.embedding_dim}</td>
                    <td className="py-2 pr-4"><StatusBadge status={m.status} /></td>
                    <td className="py-2 pr-4">{m.points_indexed ?? 0} / {m.points_total ?? 0}</td>
                    <td className="py-2 pr-4">{m.recall_score != null ? m.recall_score.toFixed(3) : "-"}</td>
                    <td className="py-2 pr-4">{formatDate(m.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}