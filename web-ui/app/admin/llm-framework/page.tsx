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
} from "@/lib/api/llm-framework";

function formatBytes(value: number | null | undefined): string {
  if (value == null) return "-";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** i).toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatCapability(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold text-ink-primary">{title}</h2>
      {children}
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "active" || status === "verified"
      ? "bg-emerald-50 text-emerald-700"
      : status === "quarantined" || status === "failed"
        ? "bg-red-50 text-red-700"
        : status === "staged" || status === "pending" || status === "downloading" || status === "verifying"
          ? "bg-amber-50 text-amber-700"
          : "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function TargetsTable({ targets }: { targets: LLMInventory["targets"] }) {
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

function ArtifactsTable({
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

function InstallationsTable({ installations }: { installations: LLMInventory["installations"] }) {
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

function RoutingTable({ routing_profiles }: { routing_profiles: LLMInventory["routing_profiles"] }) {
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

function RegisterTargetForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [runtimeType, setRuntimeType] = useState("ollama");
  const [version, setVersion] = useState("");
  const [maxModels, setMaxModels] = useState("");
  const [keepAlive, setKeepAlive] = useState("");

  const mutation = useMutation({
    mutationFn: registerLLMRuntimeTarget,
    onSuccess: () => {
      setName("");
      setHost("");
      setVersion("");
      setMaxModels("");
      setKeepAlive("");
      onSuccess();
    },
  });

  return (
    <form
      className="grid gap-3 sm:grid-cols-6"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          name,
          host,
          runtime_type: runtimeType,
          version: version || null,
          max_loaded_models: maxModels ? Number(maxModels) : null,
          keep_alive_minutes: keepAlive ? Number(keepAlive) : null,
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
        placeholder="Keep alive (min)"
        value={keepAlive}
        onChange={(e) => setKeepAlive(e.target.value)}
        className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
      />
      <div className="sm:col-span-6 flex items-center gap-2">
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

function RoutingProfileForm({
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

  const mutation = useMutation({
    mutationFn: upsertLLMRoutingProfile,
    onSuccess: () => {
      setTargetId("");
      setInstallationId("");
      setPriority("1");
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
            {i.artifact_id} on {i.target_id}
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

function DeploymentsPanel({
  capabilities,
}: {
  capabilities: string[];
}) {
  const statusQuery = useQuery({
    queryKey: ["llm-framework", "status"],
    queryFn: getLLMFrameworkStatus,
  });
  const deploymentsQuery = useQuery({
    queryKey: ["llm-framework", "deployments"],
    queryFn: getLLMDeployments,
    refetchInterval: 5000,
  });
  const auditQuery = useQuery({
    queryKey: ["llm-framework", "audit-events"],
    queryFn: getLLMAuditEvents,
    refetchInterval: 5000,
  });

  const [selectedCapability, setSelectedCapability] = useState<Record<number, string>>({});

  const approveMutation = useMutation({
    mutationFn: approveLLMDeployment,
    onSuccess: () => deploymentsQuery.refetch(),
  });
  const activateMutation = useMutation({
    mutationFn: ({ deploymentId, request }: { deploymentId: number; request: { capability: string; target_id: number } }) =>
      activateLLMDeployment(deploymentId, request),
    onSuccess: () => deploymentsQuery.refetch(),
  });
  const rollbackMutation = useMutation({
    mutationFn: rollbackLLMDeployment,
    onSuccess: () => deploymentsQuery.refetch(),
  });

  const isDeploymentEnabled = statusQuery.data?.deployment_enabled ?? false;
  const requiresApproval = statusQuery.data?.two_person_approval_required ?? true;

  return (
    <div className="space-y-4">
      <Section title="Deployments">
        {!isDeploymentEnabled && <p className="text-sm text-ink-tertiary">Deployment is disabled in configuration.</p>}
        {deploymentsQuery.isLoading ? (
          <p className="text-sm text-ink-tertiary">Loading...</p>
        ) : deploymentsQuery.data?.length === 0 ? (
          <p className="text-sm text-ink-tertiary">No deployments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line-tertiary text-ink-tertiary">
                <tr>
                  <th className="py-2 pr-4 font-medium">ID</th>
                  <th className="py-2 pr-4 font-medium">Artifact</th>
                  <th className="py-2 pr-4 font-medium">Target</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Requested by</th>
                  <th className="py-2 pr-4 font-medium">Approved by</th>
                  <th className="py-2 pr-4 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-tertiary text-ink-secondary">
                {deploymentsQuery.data?.map((d: Deployment) => (
                  <tr key={d.id}>
                    <td className="py-2 pr-4">{d.id}</td>
                    <td className="py-2 pr-4 font-medium text-ink-primary">{d.artifact_name}</td>
                    <td className="py-2 pr-4">{d.target_name}</td>
                    <td className="py-2 pr-4"><StatusBadge status={d.status} /></td>
                    <td className="py-2 pr-4">{d.requested_by_user_id ?? "-"}</td>
                    <td className="py-2 pr-4">{d.approved_by_user_id ?? "-"}</td>
                    <td className="py-2 pr-4">
                      <div className="flex flex-wrap items-center gap-2">
                        {d.status === "pending" && (
                          <button
                            onClick={() => approveMutation.mutate(d.id)}
                            disabled={approveMutation.isPending}
                            className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                          >
                            {approveMutation.isPending ? "Approving…" : "Approve"}
                          </button>
                        )}
                        {d.status === "approved" && (
                          <div className="flex items-center gap-2">
                            <select
                              value={selectedCapability[d.id] || ""}
                              onChange={(e) =>
                                setSelectedCapability((prev) => ({ ...prev, [d.id]: e.target.value }))
                              }
                              className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-xs text-ink-primary"
                            >
                              <option value="">Capability</option>
                              {capabilities.map((c) => (
                                <option key={c} value={c}>
                                  {formatCapability(c)}
                                </option>
                              ))}
                            </select>
                            <button
                              onClick={() =>
                                selectedCapability[d.id] &&
                                activateMutation.mutate({
                                  deploymentId: d.id,
                                  request: { capability: selectedCapability[d.id], target_id: d.target_id },
                                })
                              }
                              disabled={!selectedCapability[d.id] || activateMutation.isPending}
                              className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                            >
                              {activateMutation.isPending ? "Activating…" : "Activate"}
                            </button>
                          </div>
                        )}
                        {(d.status === "active" || d.status === "stabilizing") && (
                          <button
                            onClick={() => rollbackMutation.mutate(d.id)}
                            disabled={rollbackMutation.isPending}
                            className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                          >
                            {rollbackMutation.isPending ? "Rolling back…" : "Rollback"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Audit events">
        {auditQuery.isLoading ? (
          <p className="text-sm text-ink-tertiary">Loading...</p>
        ) : auditQuery.data?.length === 0 ? (
          <p className="text-sm text-ink-tertiary">No audit events yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line-tertiary text-ink-tertiary">
                <tr>
                  <th className="py-2 pr-4 font-medium">Action</th>
                  <th className="py-2 pr-4 font-medium">Entity</th>
                  <th className="py-2 pr-4 font-medium">Actor</th>
                  <th className="py-2 pr-4 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-tertiary text-ink-secondary">
                {auditQuery.data?.map((e: AuditEvent) => (
                  <tr key={e.id}>
                    <td className="py-2 pr-4 font-medium text-ink-primary">{e.action}</td>
                    <td className="py-2 pr-4">{e.entity_type} {e.entity_id ?? "-"}</td>
                    <td className="py-2 pr-4">{e.actor_user_id ?? "system"}</td>
                    <td className="py-2 pr-4">{formatDate(e.created_at)}</td>
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

function CatalogPanel() {
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

function CatalogResultCard({
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

function MigrationsPanel() {
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

function ConversionsPanel() {
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

export default function LLMFrameworkPage() {
  const [tab, setTab] = useState<"inventory" | "catalog" | "migrations" | "conversions" | "deployments">("inventory");

  const statusQuery = useQuery({
    queryKey: ["llm-framework", "status"],
    queryFn: getLLMFrameworkStatus,
  });
  const inventoryQuery = useQuery({
    queryKey: ["llm-framework", "inventory"],
    queryFn: getLLMInventory,
    refetchInterval: tab === "inventory" || tab === "deployments" ? 5000 : false,
  });
  const capabilitiesQuery = useQuery({
    queryKey: ["llm-framework", "capabilities"],
    queryFn: getLLMCapabilities,
  });

  const isLoading = statusQuery.isLoading || inventoryQuery.isLoading;
  const isCatalogEnabled = statusQuery.data?.hf_catalog_enabled;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-ink-primary">LLM Framework</h1>
        <p className="mt-1 text-sm text-ink-tertiary">
          Offline model vault, runtime targets, and routing inventory.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-ink-tertiary">Loading…</p>
      ) : statusQuery.error ? (
        <p className="text-sm text-red-600">Unable to load LLM Framework status.</p>
      ) : statusQuery.data?.enabled === false ? (
        <p className="text-sm text-ink-tertiary">LLM Framework is disabled.</p>
      ) : (
        <>
          <div className="flex gap-2 border-b border-line-tertiary">
            <button
              onClick={() => setTab("inventory")}
              className={`px-4 py-2 text-sm font-medium ${
                tab === "inventory"
                  ? "border-b-2 border-brand-600 text-brand-700"
                  : "text-ink-tertiary hover:text-ink-primary"
              }`}
            >
              Inventory
            </button>
            <button
              onClick={() => setTab("catalog")}
              className={`px-4 py-2 text-sm font-medium ${
                tab === "catalog"
                  ? "border-b-2 border-brand-600 text-brand-700"
                  : "text-ink-tertiary hover:text-ink-primary"
              }`}
            >
              Catalog
            </button>
            <button
              onClick={() => setTab("migrations")}
              className={`px-4 py-2 text-sm font-medium ${
                tab === "migrations"
                  ? "border-b-2 border-brand-600 text-brand-700"
                  : "text-ink-tertiary hover:text-ink-primary"
              }`}
            >
              Migrations
            </button>
            <button
              onClick={() => setTab("deployments")}
              className={`px-4 py-2 text-sm font-medium ${
                tab === "deployments"
                  ? "border-b-2 border-brand-600 text-brand-700"
                  : "text-ink-tertiary hover:text-ink-primary"
              }`}
            >
              Deployments
            </button>
            <button
              onClick={() => setTab("conversions")}
              className={`px-4 py-2 text-sm font-medium ${
                tab === "conversions"
                  ? "border-b-2 border-brand-600 text-brand-700"
                  : "text-ink-tertiary hover:text-ink-primary"
              }`}
            >
              Conversions
            </button>
          </div>

          {tab === "inventory" ? (
            <>
              <Section title="Status">
                <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
                  <div>
                    <div className="text-ink-tertiary">Enabled</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.enabled ? "Yes" : "No"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Catalog</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.gguf_only ? "GGUF only" : "Any"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Deployment</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.deployment_enabled ? "Enabled" : "Disabled"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Two-person approval</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.two_person_approval_required ? "Required" : "Not required"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Auto rollback</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.auto_rollback_enabled ? "Enabled" : "Disabled"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Embedding migration</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.embedding_migration_enabled ? "Enabled" : "Disabled"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">FP16 conversion</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.fp16_conversion_enabled ? "Enabled" : "Disabled"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Dynamic routing</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.dynamic_routing_enabled ? "Enabled" : "Disabled"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Recall threshold</div>
                    <div className="font-medium text-ink-primary">
                      {statusQuery.data?.embedding_recall_threshold ?? "-"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-tertiary">Signing key fingerprint</div>
                    <div className="truncate font-medium text-ink-primary">
                      {statusQuery.data?.manifest_signing_key_fingerprint || "-"}
                    </div>
                  </div>
                </div>
              </Section>

              <Section title="Capabilities">
                <div className="flex flex-wrap gap-2">
                  {capabilitiesQuery.data?.capabilities.map((cap) => (
                    <span
                      key={cap}
                      className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700"
                    >
                      {formatCapability(cap)}
                    </span>
                  ))}
                </div>
              </Section>

              {inventoryQuery.data && (
                <>
                  <Section title="Runtime targets">
                    <RegisterTargetForm onSuccess={() => inventoryQuery.refetch()} />
                    <div className="mt-4">
                      <TargetsTable targets={inventoryQuery.data.targets} />
                    </div>
                  </Section>
                  <Section title="Model artifacts">
                    <ArtifactsTable
                      artifacts={inventoryQuery.data.artifacts}
                      targets={inventoryQuery.data.targets}
                      deploymentEnabled={statusQuery.data?.deployment_enabled ?? false}
                      onInstall={() => inventoryQuery.refetch()}
                    />
                  </Section>
                  <Section title="Installations">
                    <InstallationsTable installations={inventoryQuery.data.installations} />
                  </Section>
                  <Section title="Routing profiles">
                    {statusQuery.data?.dynamic_routing_enabled ? (
                      <>
                        <RoutingProfileForm
                          capabilities={capabilitiesQuery.data?.capabilities ?? []}
                          targets={inventoryQuery.data.targets}
                          installations={inventoryQuery.data.installations}
                          onSuccess={() => inventoryQuery.refetch()}
                        />
                        <div className="mt-4">
                          <RoutingTable routing_profiles={inventoryQuery.data.routing_profiles} />
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="text-sm text-ink-tertiary">Dynamic routing is disabled in configuration.</p>
                        <div className="mt-4">
                          <RoutingTable routing_profiles={inventoryQuery.data.routing_profiles} />
                        </div>
                      </>
                    )}
                  </Section>
                </>
              )}
            </>
          ) : tab === "catalog" ? (
            isCatalogEnabled ? (
              <Section title="Hugging Face Catalog">
                <CatalogPanel />
              </Section>
            ) : (
              <p className="text-sm text-ink-tertiary">Catalog is disabled.</p>
            )
          ) : tab === "migrations" ? (
            <MigrationsPanel />
          ) : tab === "deployments" ? (
            <DeploymentsPanel capabilities={capabilitiesQuery.data?.capabilities ?? []} />
          ) : (
            <ConversionsPanel />
          )}
        </>
      )}
    </div>
  );
}
