"use client";


import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  registerLLMRuntimeTarget,
  upsertLLMRoutingProfile,
  type LLMInventory,
  type RuntimeTarget,
} from "@/lib/api/llm-framework";import { formatCapability } from "./utils";



export function RegisterTargetForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [runtimeType, setRuntimeType] = useState("ollama");
  const [version, setVersion] = useState("");
  const [maxModels, setMaxModels] = useState("");
  const [keepAlive, setKeepAlive] = useState("");
  const [environment, setEnvironment] = useState("");
  const [gpuMemoryGb, setGpuMemoryGb] = useState("");
  const [systemRamGb, setSystemRamGb] = useState("");
  const [diskGb, setDiskGb] = useState("");
  const [maxConcurrency, setMaxConcurrency] = useState("");
  const [contextTokens, setContextTokens] = useState("");

  const mutation = useMutation({
    mutationFn: registerLLMRuntimeTarget,
    onSuccess: () => {
      setName("");
      setHost("");
      setVersion("");
      setMaxModels("");
      setKeepAlive("");
      setEnvironment("");
      setGpuMemoryGb("");
      setSystemRamGb("");
      setDiskGb("");
      setMaxConcurrency("");
      setContextTokens("");
      onSuccess();
    },
  });

  return (
    <form
      className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          name,
          host,
          runtime_type: runtimeType,
          version: version || null,
          max_loaded_models: maxModels ? Number(maxModels) : null,
          keep_alive_minutes: keepAlive ? Number(keepAlive) : null,
          environment: environment || null,
          gpu_memory_gb: gpuMemoryGb ? Number(gpuMemoryGb) : null,
          system_ram_gb: systemRamGb ? Number(systemRamGb) : null,
          disk_gb: diskGb ? Number(diskGb) : null,
          max_concurrency: maxConcurrency ? Number(maxConcurrency) : null,
          context_tokens: contextTokens ? Number(contextTokens) : null,
        });
      }}
    >
      <input
        type="text"
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
        required
      />
      <input
        type="text"
        placeholder="Host URL"
        value={host}
        onChange={(e) => setHost(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
        required
      />
      <input
        type="text"
        placeholder="Runtime type"
        value={runtimeType}
        onChange={(e) => setRuntimeType(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="text"
        placeholder="Environment"
        value={environment}
        onChange={(e) => setEnvironment(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="text"
        placeholder="Version"
        value={version}
        onChange={(e) => setVersion(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="Max loaded models"
        value={maxModels}
        onChange={(e) => setMaxModels(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="GPU memory (GB)"
        value={gpuMemoryGb}
        onChange={(e) => setGpuMemoryGb(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="System RAM (GB)"
        value={systemRamGb}
        onChange={(e) => setSystemRamGb(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="Disk (GB)"
        value={diskGb}
        onChange={(e) => setDiskGb(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="Max concurrency"
        value={maxConcurrency}
        onChange={(e) => setMaxConcurrency(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="Context tokens"
        value={contextTokens}
        onChange={(e) => setContextTokens(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="Keep alive (min)"
        value={keepAlive}
        onChange={(e) => setKeepAlive(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <div className="sm:col-span-3 lg:col-span-6 flex items-center gap-2">
        <button
          type="submit"
          disabled={!name || !host || mutation.isPending}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Registering…" : "Register target"}
        </button>
        {mutation.isError && <p className="text-sm text-red-600">{(mutation.error as Error)?.message ?? "Failed"}</p>}
        {mutation.isSuccess && <p className="text-sm text-emerald-600">Target registered.</p>}
      </div>
    </form>
  );
}

export function RoutingProfileForm({
  capabilities,
  targets,
  installations,
  onSuccess,
}: {
  capabilities: string[];
  targets: RuntimeTarget[];
  installations: LLMInventory["installations"];
  onSuccess: () => void;
}) {
  const [capability, setCapability] = useState(capabilities[0] || "");
  const [targetId, setTargetId] = useState("");
  const [installationId, setInstallationId] = useState("");
  const [priority, setPriority] = useState("1");
  const [isActive, setIsActive] = useState(true);
  const [expectedVersion, setExpectedVersion] = useState("");

  const mutation = useMutation({
    mutationFn: upsertLLMRoutingProfile,
    onSuccess: () => {
      setTargetId("");
      setInstallationId("");
      setPriority("1");
      setExpectedVersion("");
      onSuccess();
    },
  });

  return (
    <form
      className="grid gap-3 sm:grid-cols-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (!capability || !targetId || !installationId) return;
        mutation.mutate({
          capability,
          target_id: Number(targetId),
          installation_id: Number(installationId),
          priority: Number(priority),
          is_active: isActive,
          expected_version: expectedVersion ? Number(expectedVersion) : null,
        });
      }}
    >
      <select
        value={capability}
        onChange={(e) => setCapability(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
        required
      >
        <option value="">Capability</option>
        {capabilities.map((c) => (
          <option key={c} value={c}>
            {formatCapability(c)}
          </option>
        ))}
      </select>
      <select
        value={targetId}
        onChange={(e) => setTargetId(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
        required
      >
        <option value="">Target</option>
        {targets.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      <select
        value={installationId}
        onChange={(e) => setInstallationId(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
        required
      >
        <option value="">Installation</option>
        {installations.map((i) => (
          <option key={i.id} value={i.id}>
            {i.artifact_id} on {i.target_id} ({i.deployment_mode || "unknown"})
          </option>
        ))}
      </select>
      <input
        type="number"
        placeholder="Priority"
        value={priority}
        onChange={(e) => setPriority(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <input
        type="number"
        placeholder="Expected version (opt.)"
        value={expectedVersion}
        onChange={(e) => setExpectedVersion(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <label className="flex items-center gap-2 text-sm text-ink-primary">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
          className="rounded border-line-tertiary"
        />
        Active
      </label>
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={!capability || !targetId || !installationId || mutation.isPending}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Saving…" : "Save routing profile"}
        </button>
        {mutation.isError && <p className="text-sm text-red-600">{(mutation.error as Error)?.message ?? "Failed"}</p>}
        {mutation.isSuccess && <p className="text-sm text-emerald-600">Profile saved.</p>}
      </div>
    </form>
  );
}