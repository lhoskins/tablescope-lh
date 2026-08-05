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
} from "@/lib/api/llm-framework";import { formatBytes, formatDate, Section, StatusBadge } from "./utils";



export function ConversionsPanel() {
  const [repoUrl, setRepoUrl] = useState("");
  const [quantization, setQuantization] = useState("Q4_K_M");

  const statusQuery = useQuery({
    queryKey: ["llm-framework", "status"],
    queryFn: getLLMFrameworkStatus,
  });
  const query = useQuery({
    queryKey: ["llm-framework", "model-conversions"],
    queryFn: getLLMModelConversions,
    refetchInterval: 5000,
  });
  const mutation = useMutation({
    mutationFn: (payload: { repo_url: string; quantization: string }) => convertLLMCatalogEntry(payload),
    onSuccess: () => query.refetch(),
  });

  const isEnabled = statusQuery.data?.fp16_conversion_enabled ?? false;

  return (
    <div className="space-y-4">
      <Section title="Start FP16 to GGUF conversion">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            placeholder="Hugging Face repo URL (e.g. https://huggingface.co/org/model)"
            className="flex-1 rounded-md border border-line-tertiary px-3 py-2 text-sm"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
          />
          <input
            type="text"
            placeholder="Quantization"
            className="rounded-md border border-line-tertiary px-3 py-2 text-sm"
            value={quantization}
            onChange={(e) => setQuantization(e.target.value)}
          />
          <button
            onClick={() => mutation.mutate({ repo_url: repoUrl, quantization })}
            disabled={!repoUrl || mutation.isPending}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Starting..." : "Convert"}
          </button>
        </div>
        {mutation.isError && <p className="text-sm text-red-600">{(mutation.error as Error)?.message ?? "Failed to start"}</p>}
        {mutation.isSuccess && (
          <p className="text-sm text-emerald-600">
            Conversion {mutation.data.conversion_id} queued (source artifact {mutation.data.source_artifact_id}).
          </p>
        )}
        {!isEnabled && <p className="text-sm text-ink-tertiary">FP16 conversion is disabled in configuration.</p>}
      </Section>

      <Section title="FP16 to GGUF conversions">
        {query.isLoading ? (
          <p className="text-sm text-ink-tertiary">Loading...</p>
        ) : query.data?.length === 0 ? (
          <p className="text-sm text-ink-tertiary">No conversions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line-tertiary text-ink-tertiary">
                <tr>
                  <th className="py-2 pr-4 font-medium">ID</th>
                  <th className="py-2 pr-4 font-medium">Source artifact</th>
                  <th className="py-2 pr-4 font-medium">Quantization</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Output artifact</th>
                  <th className="py-2 pr-4 font-medium">Size</th>
                  <th className="py-2 pr-4 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-tertiary text-ink-secondary">
                {query.data?.map((c) => (
                  <tr key={c.id}>
                    <td className="py-2 pr-4">{c.id}</td>
                    <td className="py-2 pr-4">{c.source_artifact_id}</td>
                    <td className="py-2 pr-4">{c.quantization ?? "-"}</td>
                    <td className="py-2 pr-4"><StatusBadge status={c.status} /></td>
                    <td className="py-2 pr-4">{c.output_artifact_id ?? "-"}</td>
                    <td className="py-2 pr-4">{formatBytes(c.output_size_bytes)}</td>
                    <td className="py-2 pr-4">{formatDate(c.updated_at)}</td>
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