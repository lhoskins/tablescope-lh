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
} from "@/lib/api/llm-framework";import { formatDate, formatCapability, Section, StatusBadge } from "./utils";



export function DeploymentsPanel({
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