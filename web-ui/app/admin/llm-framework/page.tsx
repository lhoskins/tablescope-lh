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
} from "@/lib/api/llm-framework";import { formatCapability, Section } from "./utils";
import { TargetsTable, ArtifactsTable, InstallationsTable, RoutingTable } from "./inventory-tables";
import { RegisterTargetForm, RoutingProfileForm } from "./register-forms";
import { DeploymentsPanel } from "./deployments-panel";
import { CatalogPanel } from "./catalog-panel";
import { MigrationsPanel } from "./migrations-panel";
import { ConversionsPanel } from "./conversions-panel";




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
