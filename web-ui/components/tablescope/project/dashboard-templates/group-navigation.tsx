"use client";

import { IconArrowLeft, IconLayoutDashboard } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import type { Dashboard } from "@/lib/ui/use-project-data";

export function DashboardGroupNavigation({
  groupName,
  dashboards,
  activeDashboardId,
  onSelectDashboard,
  onBack,
}: {
  groupName: string;
  dashboards: Dashboard[];
  activeDashboardId: number;
  onSelectDashboard: (dashboardId: number) => void;
  onBack: () => void;
}) {
  if (dashboards.length < 2) return null;
  return (
    <div className="mb-3 flex flex-col gap-2 rounded-lg border border-line-tertiary bg-bg-primary px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-2">
        <IconLayoutDashboard size={16} className="shrink-0 text-brand-600" />
        <div className="min-w-0">
          <div className="truncate text-small font-semibold text-ink-primary">{groupName}</div>
          <div className="text-[11px] text-ink-tertiary">Switch dashboards without returning to the overview</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="dashboard-group-navigation">Dashboard</label>
        <select id="dashboard-group-navigation" value={activeDashboardId} onChange={(event) => onSelectDashboard(Number(event.target.value))} className="h-8 min-w-[220px] rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none">
          {dashboards.map((dashboard) => <option key={dashboard.id} value={dashboard.id}>{dashboard.name}</option>)}
        </select>
        <Button variant="secondary" size="sm" onClick={onBack}>
          <IconArrowLeft size={13} />Other groups
        </Button>
      </div>
    </div>
  );
}
