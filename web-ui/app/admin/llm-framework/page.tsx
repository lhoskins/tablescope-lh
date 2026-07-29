"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getLLMFrameworkStatus,
  getLLMInventory,
  getLLMCapabilities,
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
        : status === "staged" || status === "pending"
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

export default function LLMFrameworkPage() {
  const statusQuery = useQuery({
    queryKey: ["llm-framework", "status"],
    queryFn: getLLMFrameworkStatus,
  });
  const inventoryQuery = useQuery({
    queryKey: ["llm-framework", "inventory"],
    queryFn: getLLMInventory,
  });
  const capabilitiesQuery = useQuery({
    queryKey: ["llm-framework", "capabilities"],
    queryFn: getLLMCapabilities,
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-ink-primary">LLM Framework</h1>
        <p className="mt-1 text-sm text-ink-tertiary">
          Offline model vault, runtime targets, and routing inventory.
        </p>
      </header>

      {statusQuery.isLoading || inventoryQuery.isLoading ? (
        <p className="text-sm text-ink-tertiary">Loading…</p>
      ) : statusQuery.error ? (
        <p className="text-sm text-red-600">Unable to load LLM Framework status.</p>
      ) : statusQuery.data?.enabled === false ? (
        <p className="text-sm text-ink-tertiary">LLM Framework is disabled.</p>
      ) : (
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
                  {cap}
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
      )}
    </div>
  );
}
