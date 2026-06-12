import { describe, expect, it } from "vitest";
import {
  buildRuntimeWidgetFilters,
  crossFilterToWidgetFilter,
  dateRangeToWidgetFilters,
  isFieldCompatible,
} from "./runtimeFilters";
import type { DashboardRuntimeState, WidgetConfig } from "@/components/dashboard/types";

function widget(overrides: Partial<WidgetConfig>): WidgetConfig {
  return {
    id: "w1",
    type: "bar",
    title: "T",
    dataSource: { kind: "datasource", viewName: "v" },
    xColumn: "Month",
    yColumn: "Revenue",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    colSpan: 6,
    position: 0,
    ...overrides,
  };
}

describe("isFieldCompatible", () => {
  it("matches case-insensitively", () => {
    expect(isFieldCompatible("Status", ["status", "value"])).toBe(true);
    expect(isFieldCompatible("Region", ["status", "value"])).toBe(false);
    expect(isFieldCompatible("", ["status"])).toBe(false);
  });
});

describe("crossFilterToWidgetFilter / dateRangeToWidgetFilters", () => {
  it("maps a cross-filter to an eq widget filter", () => {
    const f = crossFilterToWidgetFilter({
      id: "c1", sourceWidgetId: "w2", sourceField: "Status", value: "Open", label: "Status: Open",
    });
    expect(f).toEqual({ column: "Status", operator: "eq", value: "Open" });
  });

  it("maps a date range to gte/lte filters", () => {
    const fs = dateRangeToWidgetFilters("OrderDate", { preset: "custom", start: "2026-01-01", end: "2026-01-31" });
    expect(fs).toEqual([
      { column: "OrderDate", operator: "gte", value: "2026-01-01" },
      { column: "OrderDate", operator: "lte", value: "2026-01-31" },
    ]);
  });
});

describe("buildRuntimeWidgetFilters", () => {
  const runtime: DashboardRuntimeState = {
    dateRange: { preset: "custom", start: "2026-01-01", end: "2026-03-31" },
    crossFilters: [
      { id: "c1", sourceWidgetId: "w2", sourceField: "Status", value: "Open", label: "Status: Open" },
    ],
  };

  it("applies a compatible cross-filter to a widget that has the field", () => {
    const out = buildRuntimeWidgetFilters(widget({ id: "w1" }), runtime, ["Status", "Revenue", "Month"]);
    expect(out).toContainEqual({ column: "Status", operator: "eq", value: "Open" });
  });

  it("skips widgets that do not carry the filtered field", () => {
    const out = buildRuntimeWidgetFilters(widget({ id: "w1" }), runtime, ["Revenue", "Month"]);
    expect(out.find((f) => f.column === "Status")).toBeUndefined();
  });

  it("does not filter the source widget by its own cross-filter", () => {
    const out = buildRuntimeWidgetFilters(widget({ id: "w2" }), runtime, ["Status", "Revenue"]);
    expect(out.find((f) => f.column === "Status")).toBeUndefined();
  });

  it("applies the date range only when the widget opts in with a present field", () => {
    const w = widget({ id: "w1", dateField: { enabled: true, field: "OrderDate" } });
    const out = buildRuntimeWidgetFilters(w, runtime, ["OrderDate", "Revenue"]);
    expect(out).toContainEqual({ column: "OrderDate", operator: "gte", value: "2026-01-01" });
    expect(out).toContainEqual({ column: "OrderDate", operator: "lte", value: "2026-03-31" });
  });

  it("ignores the date range when the widget has no date field enabled", () => {
    const out = buildRuntimeWidgetFilters(widget({ id: "w1" }), runtime, ["OrderDate", "Revenue"]);
    expect(out.find((f) => f.operator === "gte")).toBeUndefined();
  });

  it("falls back to configured columns when the schema is unknown", () => {
    const out = buildRuntimeWidgetFilters(widget({ id: "w1", xColumn: "Status" }), runtime, []);
    expect(out).toContainEqual({ column: "Status", operator: "eq", value: "Open" });
  });
});
