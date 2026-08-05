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
} from "@/lib/api/llm-framework";import { formatBytes } from "./utils";



export function CatalogPanel() {
  const [query, setQuery] = useState("");
  const [selectedQuantization, setSelectedQuantization] = useState<Record<string, string>>({});
  const [staged, setStaged] = useState<{ repo_id: string; artifact_id: number; job_id: string } | null>(null);

  const searchQuery = useQuery({
    queryKey: ["llm-framework", "catalog", query],
    queryFn: () => searchLLMCatalog(query),
    enabled: true,
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
                onStage={(name) =>
                  stageMutation.mutate({
                    repoUrl: extractRepoUrl(model.repo_id),
                    quantization: selectedQuantization[model.repo_id] || undefined,
                    name,
                  })
                }
                isStaging={stageMutation.isPending}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

export function CatalogResultCard({
  model,
  selectedQuantization,
  onSelectQuantization,
  onStage,
  isStaging,
}: {
  model: CatalogSearchResult;
  selectedQuantization: string | undefined;
  onSelectQuantization: (q: string) => void;
  onStage: (name: string) => void;
  isStaging: boolean;
}) {
  const [customName, setCustomName] = useState("");
  const quants = model.gguf_files.map((f) => f.filename).filter((f) => f.endsWith(".gguf"));

  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary p-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold text-ink-primary">{model.repo_id}</h3>
          <p className="text-xs text-ink-tertiary">
            {model.tags.slice(0, 5).join(" • ") || "no tags"} • License: {model.license ?? "unknown"} •{" "}
            {model.downloads ?? 0} downloads
          </p>
          {model.description ? <p className="mt-1 text-sm text-ink-secondary">{model.description}</p> : null}
        </div>
        <div className="text-right text-sm text-ink-tertiary">
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
            onChange={(e) => setCustomName(e.target.value)}
            placeholder={model.name}
            className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
          />
        </div>
        <button
          onClick={() => onStage(customName || model.name)}
          disabled={isStaging || model.gguf_files.length === 0}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {isStaging ? "Staging…" : "Stage"}
        </button>
      </div>
    </div>
  );
}