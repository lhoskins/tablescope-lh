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
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";


export function goalDeleteImpact(
  goalId: number | null,
  goals: ProjectGoal[],
  metrics: ProjectMetric[],
  risks: ProjectRisk[],
): string {
  if (!goalId) {
    return "This will archive the success criterion.";
  }
  const goal = goals.find((g) => g.id === goalId);
  if (!goal) {
    return "This will archive the success criterion.";
  }
  const otherGoals = goals.filter(
    (g) => g.id !== goal.id && g.active,
  );
  const linkedMetrics = metrics.filter((m) =>
    m.active && goal.linked_metric_ids.includes(m.id),
  );
  const exclusiveMetrics = linkedMetrics.filter((m) =>
    !otherGoals.some((g) => g.linked_metric_ids.includes(m.id)),
  );
  const exclusiveRisks = risks.filter(
    (r) =>
      r.active &&
      r.linked_goal_ids.length === 1 &&
      r.linked_goal_ids.includes(goal.id),
  );
  const dataMatches = exclusiveMetrics.filter(
    (m) => m.source_match_status === "matched",
  ).length;

  const parts: string[] = [];
  if (exclusiveMetrics.length > 0) {
    parts.push(
      `${exclusiveMetrics.length} linked measure${exclusiveMetrics.length === 1 ? "" : "s"}`,
    );
  }
  if (exclusiveRisks.length > 0) {
    parts.push(
      `${exclusiveRisks.length} linked risk${exclusiveRisks.length === 1 ? "" : "s"}`,
    );
  }
  if (dataMatches > 0) {
    parts.push(`${dataMatches} data match${dataMatches === 1 ? "" : "es"}`);
  }

  if (parts.length === 0) {
    return "This will archive the success criterion. Linked measures and risks will remain available.";
  }
  return `This will archive the success criterion and the following linked items: ${parts.join(", ")}.`;
}