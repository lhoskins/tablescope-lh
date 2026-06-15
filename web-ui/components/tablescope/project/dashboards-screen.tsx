"use client";

import { useMemo } from "react";
import { IconSparkles, IconPlus, IconLayoutDashboard } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/ui/format";
import { accentFor } from "@/lib/ui/color";
import {
  useProjectDashboards,
  widgetCount,
  type Dashboard,
} from "@/lib/ui/use-project-data";

function isPublished(d: Dashboard): boolean {
  return d.status.toLowerCase() === "published";
}

function Thumb({ dashboard }: { dashboard: Dashboard }) {
  const accent = accentFor(String(dashboard.id));
  const heights = [40, 64, 52, 72, 48, 80, 56, 68];
  return (
    <div className="flex h-32 items-end gap-1.5 rounded-md bg-bg-secondary p-4">
      {heights.map((h, i) => (
        <div
          key={i}
          className="flex-1 rounded-sm"
          style={{
            height: `${h}%`,
            background: i % 2 === 0 ? accent : `${accent}55`,
          }}
        />
      ))}
    </div>
  );
}

export function DashboardsScreen({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectDashboards(projectId);
  const rows = useMemo(() => data ?? [], [data]);

  const published = rows.filter(isPublished).length;
  const aiCount = rows.filter((d) => d.ai_generated).length;
  const totalViews = rows.reduce((a, d) => a + (d.view_count ?? 0), 0);
  const totalWidgets = rows.reduce((a, d) => a + widgetCount(d.config), 0);

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-dashboards"
      breadcrumbLabel="Dashboards"
      actions={
        <>
          <Button variant="secondary">
            <IconSparkles size={14} />
            Generate with AI
          </Button>
          <Button variant="primary">
            <IconPlus size={14} />
            New dashboard
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Total dashboards"
            value={rows.length}
            hint={`${published} published`}
          />
          <StatTile
            label="AI-generated"
            value={aiCount}
            hint={`${rows.length - aiCount} manual`}
          />
          <StatTile label="Total views" value={totalViews} />
          <StatTile
            label="Widgets total"
            value={totalWidgets}
            hint="across all dashboards"
          />
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-small text-ink-tertiary">
            Loading dashboards…
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((d) => {
              const pub = isPublished(d);
              return (
                <Card key={d.id} className="flex flex-col overflow-hidden">
                  <div className="p-3">
                    <Thumb dashboard={d} />
                  </div>
                  <div className="flex-1 px-4 pb-3">
                    <div className="text-h3 text-ink-primary">{d.name}</div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge tone={pub ? "success" : "outline"}>
                        {pub ? "Published" : "Draft"}
                      </Badge>
                      <Badge tone={d.ai_generated ? "ai" : "neutral"}>
                        {d.ai_generated ? "AI" : "Manual"}
                      </Badge>
                      <span className="text-small text-ink-tertiary">
                        {d.view_count} views
                      </span>
                      <span className="text-small text-ink-tertiary">
                        {widgetCount(d.config)} widgets
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between border-t border-line-tertiary px-4 py-2.5">
                    <span className="text-small text-ink-tertiary">
                      Updated {timeAgo(d.updated_at)}
                    </span>
                    <div className="flex items-center gap-3 text-[12px] font-medium text-brand-700">
                      <button type="button" className="hover:underline">
                        {pub ? "Share" : "Publish"}
                      </button>
                      <button type="button" className="hover:underline">
                        Edit
                      </button>
                    </div>
                  </div>
                </Card>
              );
            })}

            <button
              type="button"
              className={cn(
                "flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line-secondary bg-bg-primary text-center hover:border-brand-500 hover:bg-brand-50/40",
              )}
            >
              <IconLayoutDashboard size={22} className="text-ink-tertiary" />
              <span className="text-h3 text-ink-secondary">New dashboard</span>
              <span className="max-w-[200px] text-small text-ink-tertiary">
                Build manually or let AI generate from your queries
              </span>
            </button>
          </div>
        )}
      </div>
    </ProjectShell>
  );
}
