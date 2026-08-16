"use client";

import { useState } from "react";
import { IconChevronDown, IconChevronRight, IconLayoutDashboard, IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
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
  onNewDashboard,
  onDeleteDashboard,
  onCreateGroup,
  onRenameGroup,
  onAddDashboardToGroup,
}: {
  groups: DashboardGroup[];
  loading: boolean;
  onOpenDashboard: (dashboardId: number) => void;
  onAddTemplate: () => void;
  onNewDashboard: () => void;
  onDeleteDashboard: (dashboard: Dashboard) => void;
  onCreateGroup: (name: string) => void;
  onRenameGroup: (group: DashboardGroup, name: string) => void;
  onAddDashboardToGroup: (group: DashboardGroup) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [editing, setEditing] = useState<string>();
  const [editingName, setEditingName] = useState("");
  const toggle = (id: string) => setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  if (loading) return <div className="py-16 text-center text-small text-ink-tertiary">Loading dashboards…</div>;
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.id} aria-labelledby={`dashboard-group-${group.id}`}>
          <div className="mb-3 flex flex-col gap-2 rounded-lg border border-line-tertiary bg-bg-primary px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
            <button type="button" onClick={() => toggle(group.id)} className="flex items-center gap-3 text-left" aria-expanded={expanded.has(group.id)}>
              {expanded.has(group.id) ? <IconChevronDown size={17} /> : <IconChevronRight size={17} />}
              <span className="grid h-10 w-10 place-items-center rounded-full bg-brand-50 text-brand-700"><DashboardTemplateIconView name={group.icon} /></span>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 id={`dashboard-group-${group.id}`} className="text-h3 text-ink-primary">{group.name}</h2>
                  <Badge tone={group.templateId ? "ai" : "neutral"}>{group.dashboards.length} dashboard{group.dashboards.length === 1 ? "" : "s"}</Badge>
                </div>
                <p className="mt-0.5 text-[11px] text-ink-tertiary">
                  {group.templateId ? "Operational Insight template collection" : "Operational Insight dashboard collection"}
                </p>
              </div>
            </button>
            <div className="flex items-center gap-1.5">
              {group.persistentId && <button type="button" onClick={() => { setEditing(group.id); setEditingName(group.name); }} className="rounded p-1.5 text-ink-tertiary"><IconPencil size={15} /></button>}
              <Button size="sm" variant="secondary" onClick={() => onAddDashboardToGroup(group)}><IconPlus size={13} />Add dashboard</Button>
            </div>
          </div>

          {editing === group.id && <div className="mb-3 flex max-w-lg gap-2"><input value={editingName} onChange={(event) => setEditingName(event.target.value)} className="h-8 flex-1 rounded border px-2" /><Button size="sm" variant="primary" onClick={() => { if (editingName.trim()) onRenameGroup(group, editingName.trim()); setEditing(undefined); }}>Save</Button></div>}
          {expanded.has(group.id) && <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {group.dashboards.map((dashboard) => (
              <DashboardCard
                key={dashboard.id}
                dashboard={dashboard}
                onOpen={() => onOpenDashboard(dashboard.id)}
                onDelete={() => onDeleteDashboard(dashboard)}
              />
            ))}
            {group.dashboards.length === 0 && <Card className="col-span-full p-5 text-center text-small text-ink-tertiary">This group is empty.</Card>}
          </div>}
        </section>
      ))}

      {groups.length === 0 && (
        <Card className="grid min-h-[220px] place-items-center p-6 text-center">
          <div>
            <IconLayoutDashboard size={24} className="mx-auto text-ink-tertiary" />
            <div className="mt-2 text-h3 text-ink-primary">Create your first dashboard collection</div>
            <p className="mt-1 text-small text-ink-tertiary">Start from an Operational Insight template grounded in this project&apos;s data.</p>
            <Button variant="primary" className="mt-4" onClick={onAddTemplate}><IconPlus size={14} />Add dashboard template</Button>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-center gap-2 border-t border-line-tertiary pt-4">
        <Button variant="primary" onClick={onAddTemplate}><IconPlus size={14} />Add dashboard template</Button>
        <Button variant="secondary" onClick={onNewDashboard}><IconPlus size={14} />Create dashboard with AI</Button>
        <Button variant="secondary" onClick={() => setCreating(true)}>Create dashboard group</Button>
      </div>
      {creating && <Card className="mx-auto flex max-w-xl gap-2 p-3"><input autoFocus value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="Group or header name" className="h-9 flex-1 rounded border px-3" /><Button variant="primary" onClick={() => { if (groupName.trim()) onCreateGroup(groupName.trim()); setGroupName(""); setCreating(false); }}>Create</Button></Card>}
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
