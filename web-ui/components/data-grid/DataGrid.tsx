"use client";

import { TablescopeDataGrid } from "@/components/data-grid/TablescopeDataGrid";
import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";

/**
 * Feature flag: set to true to use the new TanStack Table + dnd-kit grid.
 * Set to false to fall back to the legacy MUI X DataGridPremium.
 */
const USE_TANSTACK_GRID = process.env.NEXT_PUBLIC_USE_TANSTACK_GRID === "true";

type DataGridProps = {
  columns: string[];
  rows: Record<string, unknown>[];
  loading?: boolean;
  height?: number;
  columnTypes?: { field: string; name?: string; type: string }[];
};

/**
 * Thin wrapper that selects between the legacy MUI X DataGrid and the new
 * TanStack-based grid based on the `NEXT_PUBLIC_USE_TANSTACK_GRID` env var.
 */
export function DataGrid({ columns, rows, loading, height = 480, columnTypes }: DataGridProps) {
  const Grid = USE_TANSTACK_GRID ? TanStackDataGrid : TablescopeDataGrid;
  return (
    <Grid
      columns={columns}
      rows={rows}
      loading={loading}
      height={height}
      columnTypes={columnTypes}
    />
  );
}
