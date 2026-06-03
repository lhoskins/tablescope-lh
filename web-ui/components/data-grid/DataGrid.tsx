"use client";

import { TablescopeDataGrid } from "@/components/data-grid/TablescopeDataGrid";

type DataGridProps = {
  columns: string[];
  rows: Record<string, unknown>[];
  loading?: boolean;
  height?: number;
  columnTypes?: { field: string; name?: string; type: string }[];
};

/**
 * Thin wrapper around {@link TablescopeDataGrid} (MUI X Data Grid, community)
 * for plain result rendering without scope/drill-down features.
 */
export function DataGrid({ columns, rows, loading, height = 480, columnTypes }: DataGridProps) {
  return (
    <TablescopeDataGrid
      columns={columns}
      rows={rows}
      loading={loading}
      height={height}
      columnTypes={columnTypes}
    />
  );
}
