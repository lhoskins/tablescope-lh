"use client";

import { useState } from "react";
import type { DashboardFilter, ColumnInfo } from "./types";

type Props = {
  filters: DashboardFilter[];
  columns: ColumnInfo[];
  onChange: (filters: DashboardFilter[]) => void;
};

export function FilterBar({ filters, columns, onChange }: Props) {
  const [showAdd, setShowAdd] = useState(false);
  const [newColumn, setNewColumn] = useState("");
  const [newType, setNewType] = useState<DashboardFilter["filterType"]>("multi_select");

  const addFilter = () => {
    if (!newColumn) return;
    const col = columns.find((c) => c.name === newColumn);
    const filterType: DashboardFilter["filterType"] =
      col?.type === "date" ? "date_range" : col?.type === "number" ? "numeric_range" : newType;
    const newFilter: DashboardFilter = {
      id: `f-${Date.now()}`,
      column: newColumn,
      columnType: col?.type === "date" ? "date" : col?.type === "number" ? "number" : "string",
      filterType,
      value: filterType === "date_range" ? { from: "", to: "" } : filterType === "numeric_range" ? { min: "", max: "" } : [],
    };
    onChange([...filters, newFilter]);
    setShowAdd(false);
    setNewColumn("");
  };

  const removeFilter = (id: string) => {
    onChange(filters.filter((f) => f.id !== id));
  };

  const updateFilterValue = (id: string, value: unknown) => {
    onChange(filters.map((f) => (f.id === id ? { ...f, value } : f)));
  };

  if (filters.length === 0 && !showAdd) {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-white px-4 py-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Filters:</span>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="rounded-md border border-dashed border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-500 hover:border-blue-400 hover:text-blue-600"
        >
          + Add Filter
        </button>
      </div>
    );
  }

  return (
    <div className="mb-3 rounded-lg border border-slate-200 bg-white px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Filters:</span>

        {filters.map((f) => (
          <div
            key={f.id}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5"
          >
            <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${
              f.columnType === "date" ? "bg-amber-100 text-amber-700" :
              f.columnType === "number" ? "bg-green-100 text-green-700" :
              "bg-blue-100 text-blue-700"
            }`}>
              {f.columnType}
            </span>
            <span className="text-[11px] font-medium text-slate-700">{f.column}</span>

            {f.filterType === "date_range" && (
              <div className="flex items-center gap-1">
                <input
                  type="date"
                  className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
                  value={(f.value as { from: string; to: string })?.from ?? ""}
                  onChange={(e) => updateFilterValue(f.id, { ...(f.value as object), from: e.target.value })}
                />
                <span className="text-[10px] text-slate-400">to</span>
                <input
                  type="date"
                  className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
                  value={(f.value as { from: string; to: string })?.to ?? ""}
                  onChange={(e) => updateFilterValue(f.id, { ...(f.value as object), to: e.target.value })}
                />
              </div>
            )}

            {f.filterType === "numeric_range" && (
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  className="w-16 rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
                  placeholder="min"
                  value={(f.value as { min: string; max: string })?.min ?? ""}
                  onChange={(e) => updateFilterValue(f.id, { ...(f.value as object), min: e.target.value })}
                />
                <span className="text-[10px] text-slate-400">-</span>
                <input
                  type="number"
                  className="w-16 rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
                  placeholder="max"
                  value={(f.value as { min: string; max: string })?.max ?? ""}
                  onChange={(e) => updateFilterValue(f.id, { ...(f.value as object), max: e.target.value })}
                />
              </div>
            )}

            {(f.filterType === "multi_select" || f.filterType === "text") && (
              <input
                className="w-32 rounded border border-slate-200 px-1.5 py-0.5 text-[10px]"
                placeholder={f.filterType === "multi_select" ? "val1, val2, ..." : "contains..."}
                value={Array.isArray(f.value) ? (f.value as string[]).join(", ") : String(f.value ?? "")}
                onChange={(e) => {
                  if (f.filterType === "multi_select") {
                    updateFilterValue(f.id, e.target.value.split(",").map((s) => s.trim()).filter(Boolean));
                  } else {
                    updateFilterValue(f.id, e.target.value);
                  }
                }}
              />
            )}

            <button
              type="button"
              onClick={() => removeFilter(f.id)}
              className="ml-1 text-[10px] text-red-400 hover:text-red-600"
            >
              x
            </button>
          </div>
        ))}

        <button
          type="button"
          onClick={() => setShowAdd(!showAdd)}
          className="rounded-md border border-dashed border-slate-300 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:border-blue-400 hover:text-blue-600"
        >
          + Add
        </button>
      </div>

      {showAdd && (
        <div className="mt-2 flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 p-2">
          <select
            className="rounded border border-blue-200 px-2 py-1 text-[11px]"
            value={newColumn}
            onChange={(e) => setNewColumn(e.target.value)}
          >
            <option value="">Select column...</option>
            {columns.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.type})
              </option>
            ))}
          </select>
          <select
            className="rounded border border-blue-200 px-2 py-1 text-[11px]"
            value={newType}
            onChange={(e) => setNewType(e.target.value as DashboardFilter["filterType"])}
          >
            <option value="multi_select">Multi-select</option>
            <option value="date_range">Date Range</option>
            <option value="numeric_range">Numeric Range</option>
            <option value="text">Text Contains</option>
          </select>
          <button
            type="button"
            onClick={addFilter}
            disabled={!newColumn}
            className="rounded bg-blue-600 px-3 py-1 text-[11px] font-medium text-white disabled:opacity-50"
          >
            Add
          </button>
          <button
            type="button"
            onClick={() => setShowAdd(false)}
            className="text-[11px] text-slate-500 hover:text-slate-700"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
