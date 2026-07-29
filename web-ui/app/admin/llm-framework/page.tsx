"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  getLLMFrameworkStatus,
  getLLMInventory,
  getLLMCapabilities,
  searchLLMCatalog,
  stageLLMArtifact,
  type CatalogSearchResult,
  type LLMInventory,
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

function ArtifactsTable({ artifacts }: { artifacts: LLMInventory["artifacts"] }) {
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
          </tr>
        </thead>
        <tbody className="divide-y divide-line-tertiary text-ink-secondary">
          {artifacts.map((a) => (
            <tr key={a.id}>
              <td className="py-2 pr-4 font-medium text-ink-primary">{a.name}</td>
              <td className="py-2 pr-4">{a.publisher ?? "-"}</td>
              <td className="py-2 pr-4">{a.format}</td>
              <td className="py-2 pr-4">{a.quantization ?? "-"}</td>
              <td className="py-2 pr-4">{formatBytes(a.size_bytes)}</td>
              <td className="py-2 pr-4"><StatusBadge status={a.status} /></td>
              <td className="py-2 pr-4">{formatDate(a.verified_at)}</td>
            </tr>
          ))}
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

function CatalogPanel() {
  const [query, setQuery] = useState("");
  const [selectedQuantization, setSelectedQuantization] = useState<Record<string, string>>({});
  const [staged, setStaged] = useState<{ repo_id: string; artifact_id: number; job_id: string } | null>(null);

  const searchQuery = useQuery({
    queryKey: ["llm-framework", "catalog", query],
    queryFn: () => searchLLMCatalog(query),
    enabled: query.length > 0,
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

export default function LLMFrameworkPage() {
  const [tab, setTab] = useState<"inventory" | "catalog">("inventory");

  const statusQuery = useQuery({
    queryKey: ["llm-framework", "status"],
    queryFn: getLLMFrameworkStatus,
  });
  const inventoryQuery = useQuery({
    queryKey: ["llm-framework", "inventory"],
    queryFn: getLLMInventory,
    refetchInterval: tab === "catalog" ? 5000 : false,
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
                    <TargetsTable targets={inventoryQuery.data.targets} />
                  </Section>
                  <Section title="Model artifacts">
                    <ArtifactsTable artifacts={inventoryQuery.data.artifacts} />
                  </Section>
                  <Section title="Installations">
                    <InstallationsTable installations={inventoryQuery.data.installations} />
                  </Section>
                  <Section title="Routing profiles">
                    <RoutingTable routing_profiles={inventoryQuery.data.routing_profiles} />
                  </Section>
                </>
              )}
            </>
          ) : isCatalogEnabled ? (
            <Section title="Hugging Face Catalog">
              <CatalogPanel />
            </Section>
          ) : (
            <p className="text-sm text-ink-tertiary">Catalog is disabled.</p>
          )}
        </>
      )}
    </div>
  );
}
