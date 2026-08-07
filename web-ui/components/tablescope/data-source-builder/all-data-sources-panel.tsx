"use client";

import { useEffect, useState } from "react";
import {
  listAllDataSources,
  type AllDataSource,
  type AllDataSourcesFilters,
} from "@/lib/api/data-source-catalog";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { allDataSourceToSessionSource } from "./all-data-source-mapping";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const SOURCE_TYPE_OPTIONS = [
  { value: "all", label: "All types" },
  { value: "file", label: "File" },
  { value: "database_table", label: "Database table" },
  { value: "saas_object", label: "SaaS object" },
];

const ASSIGNMENT_OPTIONS = [
  { value: "all", label: "All" },
  { value: "assigned", label: "Assigned" },
  { value: "unassigned", label: "Unassigned" },
];

function SourceIcon({ sourceType }: { sourceType: string }) {
  let label = sourceType;
  if (sourceType === "database_table") label = "DB";
  if (sourceType === "saas_object") label = "SaaS";
  if (sourceType === "file") label = "File";
  return <Badge tone="neutral" size="sm">{label}</Badge>;
}

function DataSourceRow({
  item,
  selected,
  onToggle,
}: {
  item: AllDataSource;
  selected: boolean;
  onToggle: (item: AllDataSource) => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-line-tertiary p-3 hover:bg-bg-secondary/50">
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggle(item)}
        className="h-4 w-4 accent-brand"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 truncate text-sm font-medium text-ink-primary">
          {item.name}
          <SourceIcon sourceType={item.sourceType} />
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-tertiary">
          <span>{item.viewName}</span>
          {item.connectorType && <span>· {item.connectorType}</span>}
          {item.projectName && <span>· {item.projectName}</span>}
          {item.ownerName && <span>· {item.ownerName}</span>}
        </div>
      </div>
      <div className="text-xs text-ink-tertiary">
        {item.columns} {item.columns === 1 ? "col" : "cols"}
      </div>
    </div>
  );
}

export function AllDataSourcesPanel({ projectId }: { projectId?: string }) {
  const [filters, setFilters] = useState<AllDataSourcesFilters>({
    project_id: projectId ? Number(projectId) : undefined,
    limit: 10,
  });
  const [items, setItems] = useState<AllDataSource[]>([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const activeView = useBuilderStore((s) => s.activeView);
  const selectAllDataSource = useBuilderStore((s) => s.selectAllDataSource);
  const deselectAllDataSource = useBuilderStore((s) => s.deselectAllDataSource);
  const isAllDataSourceSelected = useBuilderStore((s) => s.isAllDataSourceSelected);

  useEffect(() => {
    if (activeView !== "all") return;
    setLoading(true);
    listAllDataSources(filters)
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
        setNextCursor(res.next_cursor);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [filters, activeView]);

  const toggle = (item: AllDataSource) => {
    if (isAllDataSourceSelected(item.id)) {
      deselectAllDataSource(item.id);
      return;
    }
    selectAllDataSource(item.id, allDataSourceToSessionSource(item));
  };

  const setFilter = (patch: Partial<AllDataSourcesFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch, cursor: undefined }));
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          placeholder="Search sources..."
          value={filters.search ?? ""}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFilter({ search: e.target.value })
          }
          className="h-8 w-64 rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-100 focus:outline-none focus:ring-2 focus:ring-brand-100"
        />
        <select
          value={filters.source_type ?? "all"}
          onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
            setFilter({
              source_type:
                e.target.value === "all" ? undefined : e.target.value,
            })
          }
          className="h-8 w-40 rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-100 focus:outline-none focus:ring-2 focus:ring-brand-100"
        >
          {SOURCE_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={filters.assignment ?? "all"}
          onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
            setFilter({
              assignment:
                e.target.value === "all"
                  ? undefined
                  : (e.target.value as AllDataSourcesFilters["assignment"]),
            })
          }
          className="h-8 w-44 rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-100 focus:outline-none focus:ring-2 focus:ring-brand-100"
        >
          {ASSIGNMENT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="text-sm text-ink-tertiary">Loading...</div>
      ) : items.length === 0 ? (
        <div className="text-sm text-ink-tertiary">No data sources found.</div>
      ) : (
        <>
          <div className="space-y-2">
            {items.map((item) => (
              <DataSourceRow
                key={item.id}
                item={item}
                selected={isAllDataSourceSelected(item.id)}
                onToggle={toggle}
              />
            ))}
          </div>
          <div className="flex items-center justify-between pt-2 text-xs text-ink-tertiary">
            <span>
              {items.length} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={!filters.cursor}
                onClick={() =>
                  setFilters((prev) => {
                    const { cursor: _, ...rest } = prev;
                    return rest;
                  })
                }
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!nextCursor}
                onClick={() =>
                  setFilters((prev) => ({ ...prev, cursor: nextCursor ?? undefined }))
                }
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
