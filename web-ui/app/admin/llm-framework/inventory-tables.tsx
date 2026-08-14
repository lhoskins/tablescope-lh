"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  installLLMArtifact,
  preflightLLMInstall,
  type LLMInventory,
  type RuntimeTarget,
  LLMDeploymentMode,
  type LLMDeploymentModeType,
  type RuntimeOptions,
} from "@/lib/api/llm-framework";
import { formatBytes, formatDate, StatusBadge, formatCapability } from "./utils";

const DEPLOYMENT_MODES = [
  { value: LLMDeploymentMode.INSTALL_ONLY, label: "Install only" },
  { value: LLMDeploymentMode.INSTALL_AND_STAGE, label: "Install and stage for canary" },
  { value: LLMDeploymentMode.INSTALL_AND_REQUEST_ACTIVATION, label: "Install and request activation" },
  { value: LLMDeploymentMode.REPLACE_ACTIVE_MODEL, label: "Replace active model" },
];

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
            <th className="py-2 pr-4 font-medium">Environment</th>
            <th className="py-2 pr-4 font-medium">GPU GB</th>
            <th className="py-2 pr-4 font-medium">RAM GB</th>
            <th className="py-2 pr-4 font-medium">Disk GB</th>
            <th className="py-2 pr-4 font-medium">Max Concurrency</th>
            <th className="py-2 pr-4 font-medium">Context Tokens</th>
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
              <td className="py-2 pr-4">{t.environment ?? "-"}</td>
              <td className="py-2 pr-4">{t.gpu_memory_gb ?? "-"}</td>
              <td className="py-2 pr-4">{t.system_ram_gb ?? "-"}</td>
              <td className="py-2 pr-4">{t.disk_gb ?? "-"}</td>
              <td className="py-2 pr-4">{t.max_concurrency ?? "-"}</td>
              <td className="py-2 pr-4">{t.context_tokens ?? "-"}</td>
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

function RuntimeOptionsInputs({
  value,
  onChange,
}: {
  value: RuntimeOptions;
  onChange: (v: RuntimeOptions) => void;
}) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 rounded-md border border-line-tertiary p-2 text-xs">
      <label className="flex flex-col gap-1 text-ink-secondary">
        Context tokens
        <input
          type="number"
          value={value.context_tokens ?? ""}
          onChange={(e) =>
            onChange({ ...value, context_tokens: e.target.value ? Number(e.target.value) : null })
          }
          className="rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-ink-primary"
        />
      </label>
      <label className="flex flex-col gap-1 text-ink-secondary">
        Max concurrency
        <input
          type="number"
          value={value.max_concurrency ?? ""}
          onChange={(e) =>
            onChange({ ...value, max_concurrency: e.target.value ? Number(e.target.value) : null })
          }
          className="rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-ink-primary"
        />
      </label>
      <label className="flex items-center gap-2 text-ink-secondary">
        <input
          type="checkbox"
          checked={!!value.vision_enabled}
          onChange={(e) => onChange({ ...value, vision_enabled: e.target.checked })}
        />
        Vision enabled
      </label>
      <label className="flex items-center gap-2 text-ink-secondary">
        <input
          type="checkbox"
          checked={!!value.speculative_decoding_enabled}
          onChange={(e) => onChange({ ...value, speculative_decoding_enabled: e.target.checked })}
        />
        Speculative decoding
      </label>
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
  const [selectedMode, setSelectedMode] = useState<Record<number, LLMDeploymentModeType>>({});
  const [runtimeOptions, setRuntimeOptions] = useState<Record<number, RuntimeOptions>>({});
  const [preflightResult, setPreflightResult] = useState<
    Record<number, { ok: boolean; detail: string | null; capacity_ok?: boolean; preflight?: any }>
  >({});

  const preflightMutation = useMutation({
    mutationFn: ({ artifactId, targetId, options }: { artifactId: number; targetId: number; options: RuntimeOptions }) =>
      preflightLLMInstall(artifactId, targetId, options),
    onSuccess: (data, variables) => {
      setPreflightResult((prev) => ({
        ...prev,
        [variables.artifactId]: {
          ok: data.target_reachable && data.disk_ok && data.slot_ok && data.capacity_ok,
          capacity_ok: data.capacity_ok,
          detail: data.detail,
          preflight: data.preflight,
        },
      }));
    },
    onError: (error: Error, variables) => {
      setPreflightResult((prev) => ({
        ...prev,
        [variables.artifactId]: { ok: false, capacity_ok: false, detail: error.message },
      }));
    },
  });

  const installMutation = useMutation({
    mutationFn: ({
      artifactId,
      request,
    }: {
      artifactId: number;
      request: { target_id: number; deployment_mode: LLMDeploymentModeType; runtime_options: RuntimeOptions };
    }) => installLLMArtifact(artifactId, request),
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
            const mode = (selectedMode[a.id] || LLMDeploymentMode.INSTALL_ONLY) as LLMDeploymentModeType;
            const options = runtimeOptions[a.id] || {};
            const preflight = preflightResult[a.id];
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
                      <div className="flex flex-wrap items-center gap-2">
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
                        <select
                          value={mode}
                          onChange={(e) =>
                            setSelectedMode((prev) => ({ ...prev, [a.id]: e.target.value as LLMDeploymentModeType }))
                          }
                          className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-sm text-ink-primary"
                        >
                          {DEPLOYMENT_MODES.map((m) => (
                            <option key={m.value} value={m.value}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={() =>
                            selectedTarget[a.id] &&
                            preflightMutation.mutate({
                              artifactId: a.id,
                              targetId: selectedTarget[a.id],
                              options,
                            })
                          }
                          disabled={!selectedTarget[a.id] || preflightMutation.isPending}
                          className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                        >
                          {preflightMutation.isPending ? "Preflight…" : "Preflight"}
                        </button>
                        <button
                          onClick={() =>
                            selectedTarget[a.id] &&
                            installMutation.mutate({
                              artifactId: a.id,
                              request: {
                                target_id: selectedTarget[a.id],
                                deployment_mode: mode,
                                runtime_options: options,
                              },
                            })
                          }
                          disabled={
                            !selectedTarget[a.id] ||
                            installMutation.isPending ||
                            !preflight?.ok
                          }
                          className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          {installMutation.isPending ? "Installing…" : "Install"}
                        </button>
                      </div>
                      <RuntimeOptionsInputs
                        value={options}
                        onChange={(v) => setRuntimeOptions((prev) => ({ ...prev, [a.id]: v }))}
                      />
                      {preflight && (
                        <div
                          className={`text-xs ${
                            preflight.ok ? "text-emerald-600" : "text-red-600"
                          }`}
                        >
                          {preflight.ok
                            ? `Target ready${preflight.capacity_ok ? " (capacity OK)" : ""}`
                            : preflight.detail || "Preflight failed"}
                        </div>
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

export function InstallationsTable({
  installations,
  targets,
}: {
  installations: LLMInventory["installations"];
  targets: RuntimeTarget[];
}) {
  if (installations.length === 0) {
    return <p className="text-sm text-ink-tertiary">No installations on runtime targets.</p>;
  }
  const targetMap = new Map(targets.map((t) => [t.id, t]));
  const byTarget: Record<string, typeof installations> = {};
  for (const i of installations) {
    const key = targetMap.get(i.target_id)?.name || `Target ${i.target_id}`;
    byTarget[key] = byTarget[key] || [];
    byTarget[key].push(i);
  }
  return (
    <div className="space-y-4">
      {Object.entries(byTarget).map(([targetName, items]) => (
        <div key={targetName}>
          <h4 className="text-sm font-semibold text-ink-primary">{targetName}</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line-tertiary text-ink-tertiary">
                <tr>
                  <th className="py-2 pr-4 font-medium">Artifact</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Deployment Mode</th>
                  <th className="py-2 pr-4 font-medium">Ollama Name</th>
                  <th className="py-2 pr-4 font-medium">Installed</th>
                  <th className="py-2 pr-4 font-medium">Activated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-tertiary text-ink-secondary">
                {items.map((i) => (
                  <tr key={i.id}>
                    <td className="py-2 pr-4 font-medium text-ink-primary">{i.artifact_id}</td>
                    <td className="py-2 pr-4"><StatusBadge status={i.status} /></td>
                    <td className="py-2 pr-4">{i.deployment_mode ?? "-"}</td>
                    <td className="py-2 pr-4">{i.ollama_model_name ?? "-"}</td>
                    <td className="py-2 pr-4">{formatDate(i.installed_at)}</td>
                    <td className="py-2 pr-4">{formatDate(i.activated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

export function RoutingTable({
  routing_profiles,
  installations,
  targets,
}: {
  routing_profiles: LLMInventory["routing_profiles"];
  installations: LLMInventory["installations"];
  targets: LLMInventory["targets"];
}) {
  if (routing_profiles.length === 0) {
    return <p className="text-sm text-ink-tertiary">No active routing profiles.</p>;
  }
  const targetMap = new Map(targets.map((t) => [t.id, t]));
  const installationMap = new Map(installations.map((i) => [i.id, i]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line-tertiary text-ink-tertiary">
          <tr>
            <th className="py-2 pr-4 font-medium">Capability</th>
            <th className="py-2 pr-4 font-medium">Target</th>
            <th className="py-2 pr-4 font-medium">Installation</th>
            <th className="py-2 pr-4 font-medium">Active</th>
            <th className="py-2 pr-4 font-medium">Version</th>
            <th className="py-2 pr-4 font-medium">Priority</th>
            <th className="py-2 pr-4 font-medium">Deployment</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-tertiary text-ink-secondary">
          {routing_profiles.map((r) => {
            const target = targetMap.get(r.target_id);
            const installation = r.installation_id ? installationMap.get(r.installation_id) : null;
            return (
              <tr key={r.id}>
                <td className="py-2 pr-4 font-medium text-ink-primary">{formatCapability(r.capability)}</td>
                <td className="py-2 pr-4">{target?.name ?? r.target_id}</td>
                <td className="py-2 pr-4">{installation?.ollama_model_name ?? r.installation_id ?? "-"}</td>
                <td className="py-2 pr-4">{r.is_active ? "Yes" : "No"}</td>
                <td className="py-2 pr-4">{r.version}</td>
                <td className="py-2 pr-4">{r.priority}</td>
                <td className="py-2 pr-4">{r.deployment_id ?? "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
