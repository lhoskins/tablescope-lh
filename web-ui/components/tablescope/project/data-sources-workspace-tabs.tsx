"use client";

import { useRouter } from "next/navigation";
import { ActionCard, ActionCenter } from "./action-center";

export type DataSourcesTab = "builder" | "connected" | "all";

/**
 * The three-way switch inside a project's "Data Sources" area, reached from
 * the top-nav grid's "Data Sources" button:
 *
 *  - Data Builder: QuickAddDataSourceWorkspace -- a streamlined,
 *    single-screen way to stage sources from any method and auto-assign
 *    them to this project. Deliberately NOT the original 2-step
 *    DataSourceBuilderWorkspace wizard, which stays unchanged as the
 *    project sidebar's "Tools > Data Source Builder" entry.
 *  - Connected Sources: the existing "Connected Sources" section (plus the
 *    "Active/All Data Sources" picker) from that original wizard, broken
 *    out as its own tab.
 *  - All Data Sources: the project's existing data sources table (the
 *    previous default behavior of the "Data Sources" nav button).
 */
export function DataSourcesWorkspaceTabs({
  projectId,
  active,
}: {
  projectId: string;
  active: DataSourcesTab;
}) {
  const router = useRouter();
  const base = `/projects/${projectId}/data-sources`;

  const go = (tab: DataSourcesTab) => {
    router.push(tab === "all" ? base : `${base}?tab=${tab}`);
  };

  return (
    <ActionCenter label="Data Sources views">
      <div className="flex items-stretch gap-2">
        <ActionCard
          lines={["Data Builder"]}
          active={active === "builder"}
          onClick={() => go("builder")}
        />
        <ActionCard
          lines={["Connected Sources"]}
          active={active === "connected"}
          onClick={() => go("connected")}
        />
        <ActionCard
          lines={["All Data Sources"]}
          active={active === "all"}
          onClick={() => go("all")}
        />
      </div>
    </ActionCenter>
  );
}
