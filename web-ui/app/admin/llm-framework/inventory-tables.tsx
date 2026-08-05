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
} from "@/lib/api/llm-framework";import { formatBytes, formatDate, StatusBadge } from "./utils";



export function TargetsTable({ targets }: { targets: LLMInventory["targets"] }) {
  if (targets.length === 0) {
    return <p className="text-sm text-ink-tertiary">No runtime targets configured.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line-tertiary text-ink-tertiary">
          <tr>
            <th className="py-2 pr-4 font-medium">Name</th>
            <th className="py-2 pr-4 font-medium">Type</th>
            <th className="py-2 pr-4 font-medium">Host</th>
            <th className="py-2 pr-4 font-medium">Version</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Reachable</th>
            <th className="py-2 pr-4 font-medium">Last seen</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-tertiary text-ink-secondary">
          {targets.map((t) => (
            <tr key={t.id}>
              <td className="py-2 pr-4 font-medium text-ink-primary">{t.name}</td>
              <td className="py-2 pr-4">{t.runtime_type}</td>
              <td className="py-2 pr-4">{t.host}</td>
              <td className="py-2 pr-4">{t.version ?? "-"}</td>
              <td className="py-2 pr-4"><StatusBadge status={t.status} /></td>
              <td className="py-2 pr-4">{t.is_reachable ? "Yes" : "No"}</td>
              <td className="py-2 pr-4">{formatDate(t.last_seen_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ArtifactsTable({
  artifacts,
  targets,
  deploymentEnabled,
  onInstall,
}: {
  artifacts: LLMInventory["artifacts"];
  targets: RuntimeTarget[];
  deploymentEnabled: boolean;
  onInstall: () => void;
}) {
  const [selectedTarget, setSelectedTarget] = useState<Record<number, number>>({});
  const [preflightResult, setPreflightResult] = useState<Record<number, { ok: boolean; detail: string | null }>>({});

  const preflightMutation = useMutation({
    mutationFn: ({ artifactId, targetId }: { artifactId: number; targetId: number }) =>
      preflightLLMInstall(artifactId, targetId),
    onSuccess: (data, variables) => {
      setPreflightResult((prev) => ({
        ...prev,
        [variables.artifactId]: {
          ok: data.target_reachable && data.disk_ok && data.slot_ok,
          detail: data.detail,
        },
      }));
    },
    onError: (error: Error, variables) => {
      setPreflightResult((prev) => ({
        ...prev,
        [variables.artifactId]: { ok: false, detail: error.message },
      }));
    },
  });

  const installMutation = useMutation({
    mutationFn: ({ artifactId, targetId }: { artifactId: number; targetId: number }) =>
      installLLMArtifact(artifactId, targetId),
    onSuccess: () => onInstall(),
  });

  if (artifacts.length === 0) {
    return <p className="text-sm text-ink-tertiary">No model artifacts in the vault.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line-tertiary text-ink-tertiary">
          <tr>
            <th className="py-2 pr-4 font-medium">Name</th>
            <th className="py-2 pr-4 font-medium">Publisher</th>
            <th className="py-2 pr-4 font-medium">Format</th>
            <th className="py-2 pr-4 font-medium">Quantization</th>
            <th className="py-2 pr-4 font-medium">Size</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Verified</th>
            <th className="py-2 pr-4 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-tertiary text-ink-secondary">
          {artifacts.map((a) => {
            const canInstall = a.status === "verified" && deploymentEnabled && targets.length > 0;
            return (
              <tr key={a.id}>
                <td className="py-2 pr-4 font-medium text-ink-primary">{a.name}</td>
                <td className="py-2 pr-4">{a.publisher ?? "-"}</td>
                <td className="py-2 pr-4">{a.format}</td>
                <td className="py-2 pr-4">{a.quantization ?? "-"}</td>
                <td className="py-2 pr-4">{formatBytes(a.size_bytes)}</td>
                <td className="py-2 pr-4"><StatusBadge status={a.status} /></td>
                <td className="py-2 pr-4">{formatDate(a.verified_at)}</td>
                <td className="py-2 pr-4">
                  {canInstall ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-2">
                        <select
                          value={selectedTarget[a.id] || ""}
                          onChange={(e) =>
                            setSelectedTarget((prev) => ({ ...prev, [a.id]: Number(e.target.value) }))
                          }
                          className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
                        >
                          <option value="">Select target</option>
                          {targets.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={() =>
                            selectedTarget[a.id] &&
                            preflightMutation.mutate({ artifactId: a.id, targetId: selectedTarget[a.id] })
                          }
                          disabled={!selectedTarget[a.id] || preflightMutation.isPending}
                          className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                        >
                          {preflightMutation.isPending ? "Preflight…" : "Preflight"}
                        </button>
                        <button
                          onClick={() =>
                            selectedTarget[a.id] &&
                            installMutation.mutate({ artifactId: a.id, targetId: selectedTarget[a.id] })
                          }
                          disabled={
                            !selectedTarget[a.id] ||
                            installMutation.isPending ||
                            !preflightResult[a.id]?.ok
                          }
                          className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          {installMutation.isPending ? "Installing…" : "Install"}
                        </button>
                      </div>
                      {preflightResult[a.id] && (
                        <p
                          className={`text-xs ${
                            preflightResult[a.id].ok ? "text-emerald-600" : "text-red-600"
                          }`}
                        >
                          {preflightResult[a.id].ok
                            ? "Target ready"
                            : preflightResult[a.id].detail || "Preflight failed"}
                        </p>
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-ink-tertiary">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function InstallationsTable({ installations }: { installations: LLMInventory["installations"] }) {
  if (installations.length === 0) {
    return <p className="text-sm text-ink-tertiary">No installations on runtime targets.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line-tertiary text-ink-tertiary">
          <tr>
            <th className="py-2 pr-4 font-medium">Artifact</th>
            <th className="py-2 pr-4 font-medium">Target</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Installed</th>
            <th className="py-2 pr-4 font-medium">Activated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-tertiary text-ink-secondary">
          {installations.map((i) => (
            <tr key={i.id}>
              <td className="py-2 pr-4 font-medium text-ink-primary">{i.artifact_id}</td>
              <td className="py-2 pr-4">{i.target_id}</td>
              <td className="py-2 pr-4"><StatusBadge status={i.status} /></td>
              <td className="py-2 pr-4">{formatDate(i.installed_at)}</td>
              <td className="py-2 pr-4">{formatDate(i.activated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RoutingTable({ routing_profiles }: { routing_profiles: LLMInventory["routing_profiles"] }) {
  if (routing_profiles.length === 0) {
    return <p className="text-sm text-ink-tertiary">No active routing profiles.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line-tertiary text-ink-tertiary">
          <tr>
            <th className="py-2 pr-4 font-medium">Capability</th>
            <th className="py-2 pr-4 font-medium">Target</th>
            <th className="py-2 pr-4 font-medium">Installation</th>
            <th className="py-2 pr-4 font-medium">Active</th>
            <th className="py-2 pr-4 font-medium">Priority</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-tertiary text-ink-secondary">
          {routing_profiles.map((r) => (
            <tr key={r.id}>
              <td className="py-2 pr-4 font-medium text-ink-primary">{r.capability}</td>
              <td className="py-2 pr-4">{r.target_id}</td>
              <td className="py-2 pr-4">{r.installation_id ?? "-"}</td>
              <td className="py-2 pr-4">{r.is_active ? "Yes" : "No"}</td>
              <td className="py-2 pr-4">{r.priority}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}