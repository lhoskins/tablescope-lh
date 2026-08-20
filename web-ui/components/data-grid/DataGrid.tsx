"use client";

import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";

type DataGridProps = {
  columns: string[];
  rows: Record<string, unknown>[];
  loading?: boolean;
  height?: number;
  total?: number;
  columnTypes?: { field: string; name?: string; type: string }[];
};

/**
 * Thin wrapper around {@link TanStackDataGrid} for plain result rendering
 * without scope/drill-down features.
 */
export function DataGrid({ columns, rows, loading, height = 480, total, columnTypes }: DataGridProps) {
  return (
    <TanStackDataGrid
      columns={columns}
      rows={rows}
      loading={loading}
      height={height}
      total={total}
      columnTypes={columnTypes}
    />
  );
}
