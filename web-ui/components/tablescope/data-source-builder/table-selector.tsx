"use client";

import { useMemo, useState } from "react";
import { IconCheck, IconSearch, IconX } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import {
  useBuilderStore,
  type SessionSource,
  type TableSelection,
  type TableState,
} from "@/lib/stores/data-source-builder-store";
import { CONNECTOR_LABELS, connectorIcon, formatCount } from "./util";

const NEXT_STATE: Record<TableState, TableState> = {
  unselected: "adding",
  adding: "unselected",
  existing: "removing",
  removing: "existing",
};

function StatusBadge({ state }: { state: TableState }) {
  switch (state) {
    case "adding":
      return <Badge tone="brand">Adding</Badge>;
    case "removing":
      return <Badge tone="danger">Removing</Badge>;
    case "existing":
      return <Badge tone="neutral">Assigned</Badge>;
    default:
      return <span className="text-ink-tertiary">—</span>;
  }
}

function TableRow({
  source,
  table,
}: {
  source: SessionSource;
  table: TableSelection;
}) {
  const updateTableState = useBuilderStore((s) => s.updateTableState);
  const clickable = true;

  const onClick = () => {
    updateTableState(source.id, table.tableName, NEXT_STATE[table.state]);
  };

  return (
    <tr
      onClick={clickable ? onClick : undefined}
      className={cn(
        "border-b border-line-tertiary text-[13px] last:border-0",
        table.state === "adding" && "bg-brand-50/30",
        table.state === "removing" && "bg-danger-bg/40",
        table.state === "existing" && "opacity-60",
        "cursor-pointer hover:bg-bg-secondary",
      )}
    >
      <td className="w-9 px-3 py-2">
        <span
          className={cn(
            "flex h-4 w-4 items-center justify-center rounded border",
            table.state === "adding" &&
              "border-brand-500 bg-brand-500 text-white",
            table.state === "removing" && "border-danger bg-danger text-white",
            table.state === "existing" &&
              "border-line-secondary bg-bg-tertiary text-ink-tertiary",
            table.state === "unselected" && "border-line-secondary",
          )}
        >
          {table.state === "adding" && <IconCheck size={11} />}
          {table.state === "removing" && <IconX size={11} />}
          {table.state === "existing" && (
            <span className="text-[10px]">–</span>
          )}
        </span>
      </td>
      <td className="px-3 py-2">
        <span
          className={cn(
            "font-mono text-[12.5px]",
            table.state === "adding" && "text-brand-700",
            table.state === "removing" && "text-danger line-through",
            table.state === "existing" && "text-ink-tertiary",
            table.state === "unselected" && "text-ink-primary",
          )}
        >
          {table.tableName}
        </span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-ink-secondary">
        {table.rows ? formatCount(table.rows) : "—"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-ink-secondary">
        {table.cols || "—"}
      </td>
      <td className="px-3 py-2 text-center text-ink-secondary">
        {table.state === "adding" || table.state === "existing"
          ? table.aiEnabled
            ? "On"
            : "Off"
          : "—"}
      </td>
      <td className="px-3 py-2 text-right">
        <StatusBadge state={table.state} />
      </td>
    </tr>
  );
}

export function TableSelector({ source }: { source: SessionSource }) {
  const clearTableSelection = useBuilderStore((s) => s.clearTableSelection);
  const selectAllTables = useBuilderStore((s) => s.selectAllTables);
  const [search, setSearch] = useState("");

  const tables = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term
      ? source.tables.filter((t) => t.tableName.toLowerCase().includes(term))
      : source.tables;
  }, [source.tables, search]);

  const adding = source.tables.filter((t) => t.state === "adding").length;
  const removing = source.tables.filter((t) => t.state === "removing").length;
  const existing = source.tables.filter((t) => t.state === "existing").length;
  const Icon = connectorIcon(source.sourceType);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-bg-secondary text-ink-secondary">
            <Icon size={18} />
          </span>
          <div>
            <p className="text-[13px] font-semibold text-ink-primary">
              {source.displayName}
            </p>
            <p className="text-caption text-ink-tertiary">
              {CONNECTOR_LABELS[source.sourceType]} · {source.tables.length}{" "}
              tables
            </p>
          </div>
        </div>
        <Badge tone="success">Connected · SSL active</Badge>
      </div>

      {/* Search */}
      <div className="px-4 pb-2">
        <div className="relative">
          <IconSearch
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search tables…"
            className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-between px-4 py-2 text-caption text-ink-tertiary">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-brand-500" /> Adding to
            project
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-danger" /> Removing from
            project
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-ink-tertiary" /> Already
            assigned
          </span>
        </div>
        <button
          type="button"
          onClick={() => selectAllTables(source.id)}
          className="font-medium text-brand-700 hover:underline"
        >
          Select all
        </button>
      </div>

      {/* Table list */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        <table className="w-full">
          <thead>
            <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
              <th className="px-3 py-2 font-medium" />
              <th className="px-3 py-2 font-medium">Table</th>
              <th className="px-3 py-2 text-right font-medium">Rows</th>
              <th className="px-3 py-2 text-right font-medium">Cols</th>
              <th className="px-3 py-2 text-center font-medium">AI</th>
              <th className="px-3 py-2 text-right font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {tables.map((t) => (
              <TableRow key={t.tableName} source={source} table={t} />
            ))}
          </tbody>
        </table>
        {tables.length === 0 && (
          <p className="py-8 text-center text-small text-ink-tertiary">
            {source.tables.length === 0
              ? `No tables found in this source.`
              : `No tables match "${search}".`}
          </p>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-line-tertiary px-4 py-2.5 text-[12px]">
        <span className="text-ink-secondary">
          <span className="font-semibold text-brand-700">{adding} adding</span> ·{" "}
          <span className="font-semibold text-danger">{removing} removing</span>{" "}
          · <span className="text-ink-tertiary">{existing} already assigned</span>
        </span>
        <button
          type="button"
          onClick={() => clearTableSelection(source.id)}
          className="font-medium text-ink-secondary hover:text-ink-primary"
        >
          Clear selection
        </button>
      </div>
    </div>
  );
}
