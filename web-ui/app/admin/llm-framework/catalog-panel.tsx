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
  getLLMCatalogDetail,
  type AuditEvent,
  type CatalogDetail,
  type CatalogSearchResult,
  type Deployment,
  type LLMInventory,
  type RuntimeTarget,
} from "@/lib/api/llm-framework";import { formatBytes } from "./utils";



export function CatalogPanel() {
  const [query, setQuery] = useState("");
  const [selectedQuantization, setSelectedQuantization] = useState<Record<string, string>>({});
  const [customNames, setCustomNames] = useState<Record<string, string>>({});
  const [staged, setStaged] = useState<{ repo_id: string; artifact_id: number; job_id: string } | null>(null);
  const [detailRepo, setDetailRepo] = useState<string | null>(null);

  const searchQuery = useQuery({
    queryKey: ["llm-framework", "catalog", query],
    queryFn: () => searchLLMCatalog(query),
    enabled: true,
  });

  const detailQuery = useQuery({
    queryKey: ["llm-framework", "catalog", "detail", detailRepo],
    queryFn: () => getLLMCatalogDetail(`https://huggingface.co/${detailRepo}`),
    enabled: !!detailRepo,
  });

  const stageMutation = useMutation({
    mutationFn: ({ repoUrl, quantization, name }: { repoUrl: string; quantization?: string; name?: string }) =>
      stageLLMArtifact({ repo_url: repoUrl, quantization, name }),
    onSuccess: (data, variables) => {
      setStaged({ repo_id: variables.repoUrl, artifact_id: data.artifact_id, job_id: data.job_id });
    },
  });

  function extractRepoUrl(repoId: string) {
    return `https://huggingface.co/${repoId}`;
  }

  const stageModel = (repoId: string) => {
    stageMutation.mutate({
      repoUrl: extractRepoUrl(repoId),
      quantization: selectedQuantization[repoId] || undefined,
      name: customNames[repoId]?.trim() || undefined,
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && searchQuery.refetch()}
          placeholder="Search Hugging Face models (e.g. Llama-3.1 GGUF)"
          className="flex-1 rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
        />
        <button
          onClick={() => searchQuery.refetch()}
          disabled={searchQuery.isFetching}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {searchQuery.isFetching ? "Searching…" : "Search"}
        </button>
      </div>

      {query === "" && (
        <p className="text-sm text-ink-tertiary">Browse popular GGUF models from Hugging Face, or type to search.</p>
      )}

      {staged && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          Staged <span className="font-medium">{staged.repo_id}</span> (artifact {staged.artifact_id}, job {staged.job_id}).
        </div>
      )}

      {searchQuery.isSuccess && (
        <div className="space-y-3">
          {searchQuery.data.length === 0 ? (
            <p className="text-sm text-ink-tertiary">No GGUF models found.</p>
          ) : (
            searchQuery.data.map((model) => (
              <CatalogResultCard
                key={model.repo_id}
                model={model}
                selectedQuantization={selectedQuantization[model.repo_id]}
                onSelectQuantization={(q) =>
                  setSelectedQuantization((prev) => ({ ...prev, [model.repo_id]: q }))
                }
                customName={customNames[model.repo_id] ?? ""}
                onCustomNameChange={(name) =>
                  setCustomNames((prev) => ({ ...prev, [model.repo_id]: name }))
                }
                onViewDetails={() => setDetailRepo(model.repo_id)}
                onStage={() => stageModel(model.repo_id)}
                isStaging={stageMutation.isPending}
              />
            ))
          )}
        </div>
      )}

      {detailRepo && (
        <CatalogDetailModal
          repoId={detailRepo}
          model={detailQuery.data}
          isLoading={detailQuery.isFetching}
          error={detailQuery.error instanceof Error ? detailQuery.error.message : null}
          selectedQuantization={selectedQuantization[detailRepo]}
          onSelectQuantization={(q) =>
            setSelectedQuantization((prev) => ({ ...prev, [detailRepo]: q }))
          }
          customName={customNames[detailRepo] ?? ""}
          onCustomNameChange={(name) =>
            setCustomNames((prev) => ({ ...prev, [detailRepo]: name }))
          }
          onStage={() => stageModel(detailRepo)}
          isStaging={stageMutation.isPending}
          onClose={() => setDetailRepo(null)}
        />
      )}
    </div>
  );
}

export function CatalogResultCard({
  model,
  selectedQuantization,
  onSelectQuantization,
  customName,
  onCustomNameChange,
  onViewDetails,
  onStage,
  isStaging,
}: {
  model: CatalogSearchResult;
  selectedQuantization: string | undefined;
  onSelectQuantization: (q: string) => void;
  customName: string;
  onCustomNameChange: (name: string) => void;
  onViewDetails: () => void;
  onStage: () => void;
  isStaging: boolean;
}) {
  const quants = model.gguf_files.map((f) => f.filename).filter((f) => f.endsWith(".gguf"));

  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary p-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="font-semibold text-ink-primary">{model.repo_id}</h3>
          <p className="text-xs text-ink-tertiary">
            {model.tags.slice(0, 5).join(" • ") || "no tags"} • License: {model.license ?? "unknown"} •{" "}
            {model.downloads ?? 0} downloads
          </p>
          {model.description ? <p className="mt-1 text-sm text-ink-secondary line-clamp-2">{model.description}</p> : null}
        </div>
        <div className="text-right text-sm text-ink-tertiary shrink-0">
          <div>{formatBytes(model.gguf_total_bytes ?? 0)} total</div>
          <div className="text-xs">{model.gguf_files.length} GGUF files</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-ink-tertiary">Quantization</label>
          <select
            value={selectedQuantization || ""}
            onChange={(e) => onSelectQuantization(e.target.value)}
            className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
          >
            <option value="">Largest GGUF</option>
            {quants.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-ink-tertiary">Display name (optional)</label>
          <input
            type="text"
            value={customName}
            onChange={(e) => onCustomNameChange(e.target.value)}
            placeholder={model.name}
            className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
          />
        </div>
        <button
          onClick={() => onStage()}
          disabled={isStaging || model.gguf_files.length === 0}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {isStaging ? "Staging…" : "Stage"}
        </button>
        <button
          onClick={onViewDetails}
          className="rounded-md border border-line-tertiary bg-bg-secondary px-4 py-2 text-sm font-medium text-ink-secondary hover:bg-bg-tertiary"
        >
          View details
        </button>
      </div>
    </div>
  );
}

function CatalogDetailModal({
  repoId,
  model,
  isLoading,
  error,
  selectedQuantization,
  onSelectQuantization,
  customName,
  onCustomNameChange,
  onStage,
  isStaging,
  onClose,
}: {
  repoId: string;
  model?: CatalogDetail;
  isLoading: boolean;
  error: string | null;
  selectedQuantization: string | undefined;
  onSelectQuantization: (q: string) => void;
  customName: string;
  onCustomNameChange: (name: string) => void;
  onStage: () => void;
  isStaging: boolean;
  onClose: () => void;
}) {
  const quants = model?.gguf_files.map((f) => f.filename).filter((f) => f.endsWith(".gguf")) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl max-h-[80vh] overflow-y-auto rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="text-h3 text-ink-primary">{repoId}</h3>
            {model && (
              <p className="text-xs text-ink-tertiary">
                License: {model.license ?? "unknown"} • {model.downloads ?? 0} downloads • {model.likes ?? 0} likes
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm text-ink-tertiary hover:bg-bg-secondary"
          >
            Close
          </button>
        </div>

        {isLoading && <p className="text-sm text-ink-tertiary">Loading details…</p>}
        {error && <p className="text-sm text-danger">{error}</p>}

        {model && (
          <div className="space-y-4">
            {model.description && (
              <div>
                <h4 className="text-xs font-medium uppercase text-ink-tertiary">Description</h4>
                <p className="mt-1 text-sm text-ink-secondary">{model.description}</p>
              </div>
            )}

            {model.readme && (
              <div>
                <h4 className="text-xs font-medium uppercase text-ink-tertiary">README</h4>
                <div className="mt-1 max-h-48 overflow-y-auto rounded-md border border-line-tertiary bg-bg-secondary p-3 text-sm text-ink-secondary whitespace-pre-wrap">
                  {model.readme}
                </div>
              </div>
            )}

            {model.tags.length > 0 && (
              <div>
                <h4 className="text-xs font-medium uppercase text-ink-tertiary">Tags</h4>
                <p className="mt-1 text-sm text-ink-secondary">{model.tags.join(" • ")}</p>
              </div>
            )}

            <div>
              <h4 className="text-xs font-medium uppercase text-ink-tertiary">Files</h4>
              <ul className="mt-1 max-h-40 overflow-y-auto rounded-md border border-line-tertiary divide-y divide-line-tertiary text-sm">
                {model.siblings.length === 0 ? (
                  <li className="px-3 py-2 text-ink-tertiary">No files listed.</li>
                ) : (
                  model.siblings.map((f) => (
                    <li key={f.filename} className="flex items-center justify-between px-3 py-2">
                      <span className="text-ink-secondary">{f.filename}</span>
                      <span className="text-xs text-ink-tertiary">{formatBytes(f.size ?? 0)}</span>
                    </li>
                  ))
                )}
              </ul>
            </div>

            <div className="flex flex-wrap items-end gap-3 border-t border-line-tertiary pt-4">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-ink-tertiary">Quantization</label>
                <select
                  value={selectedQuantization || ""}
                  onChange={(e) => onSelectQuantization(e.target.value)}
                  className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
                >
                  <option value="">Largest GGUF</option>
                  {quants.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-ink-tertiary">Display name (optional)</label>
                <input
                  type="text"
                  value={customName}
                  onChange={(e) => onCustomNameChange(e.target.value)}
                  placeholder={model.name}
                  className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
                />
              </div>
              <button
                onClick={onStage}
                disabled={isStaging || model.gguf_files.length === 0}
                className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                {isStaging ? "Staging…" : "Stage"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
