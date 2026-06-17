import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { aiStatusLabel, aiStatusTone, timeAgo } from "@/lib/ui/format";
import { accentFor } from "@/lib/ui/color";
import type { ProjectSummary } from "@/lib/ui/types";

export function RecentProjectsTable({
  projects,
}: {
  projects: ProjectSummary[];
}) {
  return (
    <section>
      <div className="flex items-center justify-between">
        <h2 className="text-h2 text-ink-primary">Recent projects</h2>
        <Link
          href="/projects"
          className="text-[13px] font-medium text-brand-500 hover:text-brand-700"
        >
          View all
        </Link>
      </div>

      <div className="mt-3 overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
              <th className="px-4 py-2.5 font-medium">Project</th>
              <th className="px-4 py-2.5 text-right font-medium">Documents</th>
              <th className="px-4 py-2.5 text-right font-medium">Queries</th>
              <th className="px-4 py-2.5 text-right font-medium">Dashboards</th>
              <th className="px-4 py-2.5 font-medium">AI Status</th>
            </tr>
          </thead>
          <tbody>
            {projects.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-ink-tertiary"
                >
                  No projects yet.{" "}
                  <Link
                    href="/projects?new=1"
                    className="text-brand-500 hover:text-brand-700"
                  >
                    Create your first project
                  </Link>
                  .
                </td>
              </tr>
            )}
            {projects.map((p) => (
              <tr
                key={p.id}
                className="border-b border-line-tertiary last:border-0 hover:bg-bg-tertiary"
              >
                <td className="px-4 py-3">
                  <Link href={`/projects/${p.id}`} className="flex items-center gap-2.5">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: p.accent ?? accentFor(p.id) }}
                    />
                    <span>
                      <span className="block font-medium text-ink-primary">
                        {p.name}
                      </span>
                      <span className="block text-small text-ink-tertiary">
                        Updated {timeAgo(p.updatedLabel)} ·{" "}
                        {p.visibility === "shared" ? "Shared" : "Private"}
                      </span>
                    </span>
                  </Link>
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                  {p.documentCount}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                  {p.queryCount}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                  {p.dashboardCount}
                </td>
                <td className="px-4 py-3">
                  <Badge tone={aiStatusTone(p.aiStatus)}>
                    {aiStatusLabel(p.aiStatus)}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
