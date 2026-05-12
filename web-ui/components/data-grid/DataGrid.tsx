"use client";

import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

type DataGridProps = {
  columns: string[];
  rows: Record<string, unknown>[];
};

export function DataGrid({ columns, rows }: DataGridProps) {
  const columnDefs = useMemo(
    () =>
      columns.map((field) => ({
        field,
        sortable: true,
        filter: true,
        resizable: true,
      })),
    [columns]
  );

  return (
    <div className="ag-theme-quartz" style={{ height: 480 }}>
      <AgGridReact
        rowData={rows}
        columnDefs={columnDefs}
        defaultColDef={{ minWidth: 120 }}
        pagination
        paginationPageSize={50}
      />
    </div>
  );
}
