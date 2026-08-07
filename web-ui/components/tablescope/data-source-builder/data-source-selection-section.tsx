"use client";

import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { cn } from "@/lib/cn";
import { ActiveSourcesTable } from "./active-sources-table";
import { AllDataSourcesPanel } from "./all-data-sources-panel";

export function DataSourceSelectionSection({
  projectId,
}: {
  projectId?: string;
}) {
  const activeView = useBuilderStore((s) => s.activeView);
  const setActiveView = useBuilderStore((s) => s.setActiveView);
  const sources = useBuilderStore((s) => s.sources);

  const createdCount = sources.length;

  return (
    <div className="mt-8 space-y-4 rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-h4 text-ink-primary">Data Sources</h2>
        <div className="inline-flex rounded-md border border-line-tertiary p-0.5">
          {(["session", "all"] as const).map((view) => (
            <button
              key={view}
              type="button"
              onClick={() => setActiveView(view)}
              className={cn(
                "px-3 py-1 text-xs font-medium transition-colors rounded-sm",
                activeView === view
                  ? "bg-brand text-white"
                  : "text-ink-secondary hover:bg-bg-secondary",
              )}
            >
              {view === "session" ? `This Session (${createdCount})` : "All Data Sources"}
            </button>
          ))}
        </div>
      </div>

      {activeView === "session" ? (
        <ActiveSourcesTable />
      ) : (
        <AllDataSourcesPanel projectId={projectId} />
      )}
    </div>
  );
}
