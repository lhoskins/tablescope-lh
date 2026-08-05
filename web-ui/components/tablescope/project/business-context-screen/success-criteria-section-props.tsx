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


export interface SuccessCriteriaSectionProps {
  goals: ProjectGoal[];
  metrics: ProjectMetric[];
  risks: ProjectRisk[];
  memberMap: Map<number, ProjectMember>;
  canEdit: boolean;
  onCreateGoal: (body: Parameters<typeof createGoal>[1]) => void;
  onUpdateGoal: (id: number, body: Parameters<typeof updateGoal>[2]) => void;
  onDeleteGoal: (id: number) => void;
  onCreateMetric: (body: Parameters<typeof createMetric>[1]) => void;
  onUpdateMetric: (id: number, body: Parameters<typeof updateMetric>[2]) => void;
  onDeleteMetric: (id: number) => void;
  onMatchMetric: (metricId: number) => void;
}