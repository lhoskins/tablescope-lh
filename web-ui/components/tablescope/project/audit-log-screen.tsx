"use client";

import { useMemo, useState } from "react";
import {
  IconSparkles,
  IconCode,
  IconDatabase,
  IconUpload,
  IconLayoutDashboard,
  IconShieldCheck,
  IconDownload,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { StatTile } from "@/components/ui/stat-tile";
import { cn } from "@/lib/cn";
import {
  useProjectActivity,
  type ActivityEvent,
} from "@/lib/ui/use-project-data";

const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "All events" },
  { key: "ai", label: "AI actions" },
  { key: "query", label: "Queries" },
  { key: "upload", label: "Data access" },
  { key: "dashboard", label: "Dashboards" },
];

const CATEGORY_META: Record<
  string,
  { icon: typeof IconCode; tone: "ai" | "brand" | "neutral" | "success" }
> = {
  ai: { icon: IconSparkles, tone: "ai" },
  query: { icon: IconCode, tone: "brand" },
  dashboard: { icon: IconLayoutDashboard, tone: "neutral" },
  upload: { icon: IconUpload, tone: "success" },
  sync: { icon: IconDatabase, tone: "neutral" },
};

function fmt(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? ts
    : d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export function ProjectAuditLogPanel({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectActivity(projectId);
  const events = useMemo(() => data?.events ?? [], [data]);
  const stats = data?.stats;
  const [filter, setFilter] = useState("all");

  const filtered = events.filter((e) =>
    filter === "all" ? true : e.category === filter,
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="secondary">
          <IconDownload size={14} />
          Export log
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Total events"
            value={stats?.total_events ?? events.length}
          />
          <StatTile label="AI actions" value={stats?.ai_actions ?? 0} />
          <StatTile label="Active users" value={stats?.active_users ?? 0} />
          <StatTile
            label="Isolation violations"
            value={stats?.isolation_violations ?? 0}
            hint="Tenant isolation enforced"
            hintTone="success"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "h-8 rounded-md border px-3 text-[12px] font-medium",
                filter === f.key
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-line-secondary bg-bg-primary text-ink-secondary hover:bg-bg-secondary",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line-tertiary px-4 py-3">
            <IconShieldCheck size={15} className="text-success" />
            <span className="text-small text-ink-secondary">
              Every action in this project is logged and scoped to your tenant.
            </span>
          </div>

          {isLoading ? (
            <div className="px-4 py-16 text-center text-small text-ink-tertiary">
              Loading audit events…
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-4 py-16 text-center text-small text-ink-tertiary">
              No events recorded yet for this filter.
            </div>
          ) : (
            <ol className="relative px-4 py-2">
              {filtered.map((e) => (
                <EventRow key={e.id} event={e} />
              ))}
            </ol>
          )}
        </Card>
      </div>
  );
}

export const AuditLogScreen = ProjectAuditLogPanel;

function EventRow({ event }: { event: ActivityEvent }) {
  const meta = CATEGORY_META[event.category] ?? CATEGORY_META.sync;
  const Icon = meta.icon;
  return (
    <li className="flex gap-3 border-b border-line-tertiary py-3 last:border-0">
      <div
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          meta.tone === "ai" && "bg-ai-bg text-ai",
          meta.tone === "brand" && "bg-brand-50 text-brand-700",
          meta.tone === "success" && "bg-success-bg text-success",
          meta.tone === "neutral" && "bg-bg-secondary text-ink-secondary",
        )}
      >
        <Icon size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px] font-medium text-ink-primary">
            {event.title}
          </span>
          <span className="shrink-0 text-small text-ink-tertiary">
            {fmt(event.ts)}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-small text-ink-tertiary">
          <Badge tone={meta.tone}>{event.label}</Badge>
          <span>{event.actor}</span>
          {event.detail && (
            <>
              <span aria-hidden>·</span>
              <span className="truncate">{event.detail}</span>
            </>
          )}
        </div>
      </div>
    </li>
  );
}
