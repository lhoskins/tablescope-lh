"use client";


import { useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  IconChartLine,
  IconChevronDown,
  IconChevronRight,
  IconClock,
  IconGauge,
  IconMinus,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconTarget,
  IconTrash,
  IconTrendingDown,
  IconTrendingUp,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import {
  getProjectContext,
  createGoal,
  updateGoal,
  deleteGoal,
  createMetric,
  updateMetric,
  deleteMetric,
  createRisk,
  updateRisk,
  deleteRisk,
  startKpiSourceMatch,
  type ProjectContext,
  type ProjectGoal,
  type ProjectMetric,
  type ProjectRisk,
  type MetricCreateRequest,
} from "@/lib/api/project-context";
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";import { metricOnTrack } from "./business-context-screen/metric-on-track";
import { SummaryCards } from "./business-context-screen/summary-cards";
import { SuccessCriteriaSection } from "./business-context-screen/success-criteria-section";
import { RisksSection } from "./business-context-screen/risks-section";



export function BusinessContextScreen({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();

  const contextQueryKey = ["project-context", projectId];
  const { data, isLoading, refetch } = useQuery<ProjectContext>({
    queryKey: contextQueryKey,
    queryFn: () => getProjectContext(projectId),
  });

  const membersQuery = useProjectMembers(projectId);
  const memberMap = useMemo(() => {
    const map = new Map<number, ProjectMember>();
    for (const m of membersQuery.data ?? []) {
      map.set(m.user_id, m);
    }
    return map;
  }, [membersQuery.data]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: contextQueryKey });
    void refetch();
  };

  const onError = (e: unknown) => {
    push(e instanceof Error ? e.message : "An unexpected error occurred", "error");
  };

  const goalCreate = useMutation({
    mutationFn: createGoal.bind(null, projectId),
    onSuccess: () => { push("Success criterion created", "success"); refresh(); },
    onError,
  });
  const goalUpdate = useMutation({
    mutationFn: (args: { goalId: number; body: Parameters<typeof updateGoal>[2] }) =>
      updateGoal(projectId, args.goalId, args.body),
    onSuccess: () => { push("Success criterion updated", "success"); refresh(); },
    onError,
  });
  const goalDelete = useMutation({
    mutationFn: deleteGoal.bind(null, projectId),
    onSuccess: () => { push("Success criterion deleted", "success"); refresh(); },
    onError,
  });

  const metricCreate = useMutation({
    mutationFn: createMetric.bind(null, projectId),
    onSuccess: () => { push("KPI created", "success"); refresh(); },
    onError,
  });
  const metricUpdate = useMutation({
    mutationFn: (args: { metricId: number; body: Parameters<typeof updateMetric>[2] }) =>
      updateMetric(projectId, args.metricId, args.body),
    onSuccess: () => { push("KPI updated", "success"); refresh(); },
    onError,
  });
  const metricDelete = useMutation({
    mutationFn: deleteMetric.bind(null, projectId),
    onSuccess: () => { push("KPI deleted", "success"); refresh(); },
    onError,
  });

  const riskCreate = useMutation({
    mutationFn: createRisk.bind(null, projectId),
    onSuccess: () => { push("Risk created", "success"); refresh(); },
    onError,
  });
  const riskUpdate = useMutation({
    mutationFn: (args: { riskId: number; body: Parameters<typeof updateRisk>[2] }) =>
      updateRisk(projectId, args.riskId, args.body),
    onSuccess: () => { push("Risk updated", "success"); refresh(); },
    onError,
  });
  const riskDelete = useMutation({
    mutationFn: deleteRisk.bind(null, projectId),
    onSuccess: () => { push("Risk deleted", "success"); refresh(); },
    onError,
  });

  const kpiMatch = useMutation({
    mutationFn: (metricId: number) => startKpiSourceMatch(projectId, metricId),
    onSuccess: (res) => push(res.message, "success"),
    onError,
  });

  const canEdit = data?.permissions.can_edit ?? false;

  const goals = data?.goals ?? [];
  const metrics = data?.metrics ?? [];
  const risks = data?.risks ?? [];

  const onTrackCount = metrics.filter((m) => metricOnTrack(m)).length;
  const onTrackPercent = metrics.length ? Math.round((onTrackCount / metrics.length) * 100) : 0;

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-business-context"
      breadcrumbLabel="Goals"
      actions={
        <Button variant="secondary" size="sm" onClick={() => void refetch()}>
          <IconRefresh size={14} />
          Refresh
        </Button>
      }
    >
      <div className="space-y-6">
        {!isLoading && (
          <div>
            <h1 className="text-2xl font-semibold text-ink-primary">Goals</h1>
            <p className="mt-1 text-sm text-ink-secondary">
              Define project success, track the KPIs that prove it, and manage project-wide risks.
            </p>
          </div>
        )}
        {isLoading ? (
          <Card>
            <CardBody>
              <div className="text-sm text-ink-secondary">Loading goals…</div>
            </CardBody>
          </Card>
        ) : (
          <>
            <SummaryCards
              goalCount={goals.length}
              kpiCount={metrics.length}
              riskCount={risks.length}
              onTrackPercent={onTrackPercent}
            />

            <SuccessCriteriaSection
              goals={goals}
              metrics={metrics}
              risks={risks}
              memberMap={memberMap}
              canEdit={canEdit}
              onCreateGoal={(body) => goalCreate.mutate(body)}
              onUpdateGoal={(id, body) => goalUpdate.mutate({ goalId: id, body })}
              onDeleteGoal={(id) => goalDelete.mutate(id)}
              onCreateMetric={(body) => metricCreate.mutate(body)}
              onUpdateMetric={(id, body) => metricUpdate.mutate({ metricId: id, body })}
              onDeleteMetric={(id) => metricDelete.mutate(id)}
              onMatchMetric={(metricId) => kpiMatch.mutate(metricId)}
            />

            <RisksSection
              risks={risks}
              memberMap={memberMap}
              canEdit={canEdit}
              onCreateRisk={(body) => riskCreate.mutate(body)}
              onUpdateRisk={(id, body) => riskUpdate.mutate({ riskId: id, body })}
              onDeleteRisk={(id) => riskDelete.mutate(id)}
            />
          </>
        )}
      </div>
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}
