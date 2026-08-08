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


export function metricTrendMeta(metric: ProjectMetric): { direction: "up" | "down" | "flat"; label: string; tone: BadgeProps["tone"] } {
  const target = metric.targets?.find((t) => t.active && t.status !== "archived");
  const current = metric.latest_value != null ? Number(metric.latest_value) : null;
  const targetValue = target?.target_value != null ? Number(target.target_value) : null;
  if (current == null || targetValue == null) return { direction: "flat", label: "—", tone: "neutral" };
  let onTrack = false;
  if (metric.directionality === "lower_is_better") onTrack = current <= targetValue;
  else if (metric.directionality === "higher_is_better") onTrack = current >= targetValue;
  else onTrack = current === targetValue;
  if (onTrack) {
    return { direction: "up", label: "Improving", tone: "success" };
  }
  return { direction: "down", label: "Watch", tone: "warning" };
}