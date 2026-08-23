"use client";

import { IconLayoutDashboard, IconPlus, IconTrash } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { timeAgo } from "@/lib/ui/format";
import { widgetCount, type Dashboard } from "@/lib/ui/use-project-data";
import { DashboardTemplateIconView } from "./icons";
import { dashboardIcon } from "./groups";
import type { DashboardGroup } from "./types";

export function DashboardOverview({
  groups,
  loading,
  onOpenDashboard,
  onAddTemplate,
  onDeleteDashboard,
}: {
  groups: DashboardGroup[];
  loading: boolean;
  onOpenDashboard: (dashboardId: number) => void;
  onAddTemplate: () => void;
  onDeleteDashboard: (dashboard: Dashboard) => void;
}) {
  if (loading) return <div className="py-16 text-center text-small text-ink-tertiary">Loading dashboards…</div>;
  const dashboards = groups.flatMap((group) => group.dashboards);
  return (
    <div className="space-y-6">
      {dashboards.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {dashboards.map((dashboard) => (
            <DashboardCard
              key={dashboard.id}
              dashboard={dashboard}
              onOpen={() => onOpenDashboard(dashboard.id)}
              onDelete={() => onDeleteDashboard(dashboard)}
            />
          ))}
        </div>
      ) : (
        <Card className="grid min-h-[220px] place-items-center p-6 text-center">
          <div>
            <IconLayoutDashboard size={24} className="mx-auto text-ink-tertiary" />
            <div className="mt-2 text-h3 text-ink-primary">Create your first dashboard</div>
            <p className="mt-1 text-small text-ink-tertiary">Start from an Operational Insight template grounded in this project&apos;s data.</p>
            <Button variant="primary" className="mt-4" onClick={onAddTemplate}><IconPlus size={14} />Add dashboard template</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function DashboardCard({
  dashboard,
  onOpen,
  onDelete,
}: {
  dashboard: Dashboard;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const published = dashboard.status.toLowerCase() === "published";
  const count = dashboard.id < 0 ? undefined : widgetCount(dashboard.config);
  return (
    <Card onClick={onOpen} className="group flex min-h-[150px] cursor-pointer items-center gap-3 p-4 transition-colors hover:border-brand-300">
      <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700"><DashboardTemplateIconView name={dashboardIcon(dashboard)} size={22} /></span>
      <div className="min-w-0 flex-1 self-center">
        <div className="text-small font-semibold text-ink-primary">{dashboard.name}</div>
        <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-ink-tertiary">{dashboard.description || "Live operational metrics, trends and supporting detail."}</div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <Badge tone={published ? "success" : "outline"}>{published ? "Live" : "Draft"}</Badge>
          {dashboard.ai_generated && <Badge tone="ai">AI</Badge>}
          {count !== undefined && <span className="text-[10px] text-ink-tertiary">{count} insight{count === 1 ? "" : "s"}</span>}
        </div>
        <div className="mt-2 text-[10px] text-ink-tertiary">Updated {timeAgo(dashboard.updated_at)}</div>
      </div>
      {dashboard.id >= 0 && (
        <button type="button" title="Delete dashboard" aria-label={`Delete dashboard ${dashboard.name}`} onClick={(event) => { event.stopPropagation(); onDelete(); }} className="self-start rounded p-1 text-ink-tertiary opacity-0 transition-opacity hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 focus:opacity-100">
          <IconTrash size={15} />
        </button>
      )}
    </Card>
  );
}
