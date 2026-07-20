"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconRefresh,
  IconHeartbeat,
  IconActivity,
  IconCheck,
  IconAlertTriangle,
  IconInfoCircle,
  IconPlayerPlay,
  IconHistory,
  IconLoader2,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatLastUpdated } from "@/lib/format-datetime";
import { knowledgeGraphApi, type KnowledgeGraphStatus } from "@/lib/api/knowledge-graph";

interface Props {
  projectId: string;
}

const STATUS_TONE: Record<string, string> = {
  active: "success",
  healthy: "success",
  ready: "success",
  stale: "warning",
  degraded: "warning",
  warning: "warning",
  failed: "danger",
  unhealthy: "danger",
  unavailable: "neutral",
  missing: "neutral",
  queued: "brand",
  building: "brand",
  validating: "brand",
};

export function KnowledgeGraphLifecycleScreen({ projectId }: Props) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"builds" | "versions" | "health">("builds");

  const statusQuery = useQuery<KnowledgeGraphStatus>({
    queryKey: ["project", projectId, "knowledge-graph", "status"],
    queryFn: () => knowledgeGraphApi.status(projectId),
    enabled: Boolean(projectId),
    refetchInterval: 5000,
  });

  const rebuild = useMutation({
    mutationFn: () => knowledgeGraphApi.rebuild(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId, "knowledge-graph"] });
    },
  });

  const healthCheck = useMutation({
    mutationFn: () => knowledgeGraphApi.runHealthCheck(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId, "knowledge-graph"] });
    },
  });

  const data = statusQuery.data;

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-knowledge-graph"
      breadcrumbLabel="Graph Lifecycle"
    >
      <div className="mx-auto w-full max-w-content space-y-4 py-4">
        <section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <IconActivity size={18} className="text-brand-500" />
              <h2 className="text-h2 text-ink-primary">Knowledge Graph Lifecycle</h2>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => healthCheck.mutate()}
                disabled={healthCheck.isPending}
              >
                {healthCheck.isPending ? (
                  <IconLoader2 size={15} className="mr-1.5 animate-spin" />
                ) : (
                  <IconHeartbeat size={15} className="mr-1.5" />
                )}
                Check Health
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => rebuild.mutate()}
                disabled={rebuild.isPending}
              >
                {rebuild.isPending ? (
                  <IconLoader2 size={15} className="mr-1.5 animate-spin" />
                ) : (
                  <IconRefresh size={15} className="mr-1.5" />
                )}
                Rebuild
              </Button>
            </div>
          </div>

          {data ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Status"
                value={data.lifecycle_status}
                tone={STATUS_TONE[data.lifecycle_status] ?? "neutral"}
                icon={IconActivity}
              />
              <StatCard
                label="Health"
                value={data.health_status}
                tone={STATUS_TONE[data.health_status] ?? "neutral"}
                icon={IconHeartbeat}
              />
              <StatCard
                label="Active version"
                value={data.active_version_number ? `v${data.active_version_number}` : "None"}
                tone={data.has_active_version ? "success" : "neutral"}
                icon={IconCheck}
              />
              <StatCard
                label="Nodes / Edges"
                value={`${data.active_node_count} / ${data.active_edge_count}`}
                tone="neutral"
                icon={IconInfoCircle}
              />
            </div>
          ) : statusQuery.isLoading ? (
            <div className="h-24 animate-pulse rounded-md bg-bg-secondary" />
          ) : null}

          {data?.active_source_fingerprint && (
            <div className="mt-4 rounded-md bg-bg-secondary px-3 py-2 text-[12px] text-ink-tertiary">
              Source fingerprint: <span className="font-mono">{data.active_source_fingerprint.slice(0, 24)}…</span>
              {data.last_successful_build_at && (
                <span className="ml-4">
                  Last build: {formatLastUpdated(data.last_successful_build_at)}
                </span>
              )}
            </div>
          )}
        </section>

        {data && (data.lifecycle_status === "failed" || data.health_status === "unhealthy") && (
          <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-bg px-3 py-2 text-[13px] text-danger">
            <IconAlertTriangle size={15} className="mt-0.5 shrink-0" />
            <div>
              The knowledge graph needs attention. Run a full rebuild from the
              Check Health or Rebuild buttons above.
            </div>
          </div>
        )}

        <section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
          <div className="mb-4 flex items-center gap-4 border-b border-line-tertiary pb-3">
            <TabButton active={activeTab === "builds"} onClick={() => setActiveTab("builds")}>
              <IconPlayerPlay size={14} className="mr-1.5" />
              Builds
            </TabButton>
            <TabButton active={activeTab === "versions"} onClick={() => setActiveTab("versions")}>
              <IconHistory size={14} className="mr-1.5" />
              Versions
            </TabButton>
            <TabButton active={activeTab === "health"} onClick={() => setActiveTab("health")}>
              <IconHeartbeat size={14} className="mr-1.5" />
              Health
            </TabButton>
          </div>

          {activeTab === "builds" && (
            <BuildsList builds={data?.builds ?? []} />
          )}
          {activeTab === "versions" && (
            <VersionsList versions={data?.versions ?? []} />
          )}
          {activeTab === "health" && (
            <HealthPanel status={data} />
          )}
        </section>
      </div>
    </ProjectShell>
  );
}

function StatCard({
  label,
  value,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  tone: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}) {
  return (
    <div className="rounded-md border border-line-tertiary bg-bg-secondary p-3">
      <div className="mb-2 flex items-center gap-2 text-[12px] text-ink-tertiary">
        <Icon size={14} />
        {label}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-h3 text-ink-primary">{value}</span>
        <Badge tone={tone as any} size="sm">
          {tone}
        </Badge>
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center text-[13px] font-medium",
        active ? "text-brand-600" : "text-ink-tertiary hover:text-ink-secondary",
      )}
    >
      {children}
    </button>
  );
}

function BuildsList({ builds }: { builds: KnowledgeGraphStatus["builds"] }) {
  if (builds.length === 0) {
    return <Empty text="No builds yet. Run a rebuild to create one." />;
  }
  return (
    <div className="space-y-2">
      {builds.map((b) => (
        <div
          key={b.id}
          className="flex items-center justify-between rounded-md border border-line-tertiary px-3 py-2"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-medium text-ink-primary">
              <Badge tone={(STATUS_TONE[b.status] ?? "neutral") as any} size="sm">
                {b.status}
              </Badge>
              <span className="truncate">{b.build_type} build</span>
            </div>
            <div className="mt-0.5 text-[12px] text-ink-tertiary">
              {b.stage} {b.progress > 0 && `(${b.progress}%)`}
              {b.error_code && <> · {b.error_code}</>}
            </div>
          </div>
          <div className="shrink-0 text-[12px] text-ink-tertiary">
            {b.created_at ? formatLastUpdated(b.created_at) : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}

function VersionsList({ versions }: { versions: KnowledgeGraphStatus["versions"] }) {
  if (versions.length === 0) {
    return <Empty text="No versions yet." />;
  }
  return (
    <div className="space-y-2">
      {versions.map((v) => (
        <div
          key={v.id}
          className="flex items-center justify-between rounded-md border border-line-tertiary px-3 py-2"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-medium text-ink-primary">
              <Badge tone={(STATUS_TONE[v.status] ?? "neutral") as any} size="sm">
                {v.status}
              </Badge>
              <span>v{v.version_number}</span>
              <span className="text-ink-tertiary">({v.build_type})</span>
            </div>
            <div className="mt-0.5 text-[12px] text-ink-tertiary">
              {v.node_count} nodes · {v.edge_count} edges
              {v.activated_at && <> · activated {formatLastUpdated(v.activated_at)}</>}
            </div>
          </div>
          <div className="shrink-0 text-[12px] text-ink-tertiary">
            {v.source_fingerprint && v.source_fingerprint.slice(0, 12)}…
          </div>
        </div>
      ))}
    </div>
  );
}

function HealthPanel({ status }: { status: KnowledgeGraphStatus | undefined }) {
  if (!status) return <Empty text="No health data." />;
  return (
    <div className="space-y-2 text-[13px]">
      <div className="flex justify-between rounded-md border border-line-tertiary px-3 py-2">
        <span className="text-ink-secondary">Last check</span>
        <span className="text-ink-primary">
          {status.last_health_check_at
            ? formatLastUpdated(status.last_health_check_at)
            : "Never"}
        </span>
      </div>
      <div className="flex justify-between rounded-md border border-line-tertiary px-3 py-2">
        <span className="text-ink-secondary">Health status</span>
        <Badge tone={(STATUS_TONE[status.health_status] ?? "neutral") as any} size="sm">
          {status.health_status}
        </Badge>
      </div>
      <div className="flex justify-between rounded-md border border-line-tertiary px-3 py-2">
        <span className="text-ink-secondary">Active nodes / edges</span>
        <span className="text-ink-primary">
          {status.active_node_count} / {status.active_edge_count}
        </span>
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-line-tertiary py-8 text-center text-[13px] text-ink-tertiary">
      {text}
    </div>
  );
}
