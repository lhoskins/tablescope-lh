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


export function SummaryCards({
  goalCount,
  kpiCount,
  riskCount,
  onTrackPercent,
}: {
  goalCount: number;
  kpiCount: number;
  riskCount: number;
  onTrackPercent: number;
}) {
  return (
    <Card>
      <CardBody className="p-0">
        <div className="grid grid-cols-1 divide-y divide-line-tertiary sm:grid-cols-2 sm:divide-y-0 sm:divide-x lg:grid-cols-4">
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{goalCount}</span>
            <span className="text-sm text-ink-secondary">Success criteria</span>
          </div>
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{kpiCount}</span>
            <span className="text-sm text-ink-secondary">KPIs</span>
          </div>
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{riskCount}</span>
            <span className="text-sm text-ink-secondary">Project risks</span>
          </div>
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{onTrackPercent}%</span>
            <span className="text-sm text-ink-secondary">On track</span>
            <div className="ml-auto h-2 w-24 overflow-hidden rounded-full bg-bg-secondary">
              <div className="h-full rounded-full bg-success" style={{ width: `${onTrackPercent}%` }} />
            </div>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}