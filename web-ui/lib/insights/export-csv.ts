import type { InsightCard } from "@/lib/api/home-intelligence";

const FORMULA_PREFIXES = /^[=+\-@]/;

export interface ExportableData {
  columns: string[];
  rows: Record<string, unknown>[];
}

function normalizeValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

function csvEscapeCell(value: unknown): string {
  const text = normalizeValue(value);
  // Formula-injection mitigation: force text treatment in spreadsheet clients.
  const safe = FORMULA_PREFIXES.test(text) ? `'${text}` : text;
  const needsQuote =
    safe.includes(",") || safe.includes('"') || safe.includes("\n") || safe.includes("\r");
  if (!needsQuote) return safe;
  return `"${safe.replace(/"/g, '""')}"`;
}

function buildCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const header = columns.map((c) => csvEscapeCell(c)).join(",");
  const lines = rows.map((row) =>
    columns.map((col) => csvEscapeCell(row[col])).join(","),
  );
  return [header, ...lines].join("\r\n");
}

export function getExportableData(card: InsightCard): ExportableData | null {
  const chart = card.chart;
  if (!chart) return null;

  if (chart.data.rows && chart.data.rows.length > 0 && chart.data.columns && chart.data.columns.length > 0) {
    return { columns: chart.data.columns, rows: chart.data.rows };
  }

  if (chart.data.series && chart.data.series.length > 0) {
    const series = chart.data.series;
    const hasValue2 = series.some((s) => typeof s.value2 === "number");
    const labelName = chart.roles?.x ?? "label";
    const valueName = chart.seriesLabels?.value ?? chart.roles?.value ?? chart.roles?.y ?? "value";
    const value2Name = chart.seriesLabels?.value2 ?? chart.roles?.y2 ?? "value2";
    const columns = hasValue2 ? [labelName, valueName, value2Name] : [labelName, valueName];
    const rows = series.map((s) => {
      const row: Record<string, unknown> = {
        [labelName]: s.label,
        [valueName]: s.value,
      };
      if (hasValue2) {
        row[value2Name] = s.value2 ?? "";
      }
      return row;
    });
    return { columns, rows };
  }

  if (chart.data.kpis && chart.data.kpis.length > 0) {
    const columns = ["label", "value", "delta"];
    const rows = chart.data.kpis.map((k) => ({
      label: k.label,
      value: k.value,
      delta: k.delta ?? "",
    }));
    return { columns, rows };
  }

  return null;
}

export function canExportInsightCsv(card: InsightCard): boolean {
  return getExportableData(card) !== null;
}

export function insightCsvFilename(card: InsightCard): string {
  const date = new Date().toISOString().slice(0, 10);
  const title = (card.title || "insight")
    .replace(/[^a-zA-Z0-9_\- ]/g, "")
    .trim()
    .replace(/\s+/g, "_")
    .slice(0, 50);
  return `${title}_${date}.csv`;
}

export async function exportInsightCardCsv(card: InsightCard): Promise<void> {
  const data = getExportableData(card);
  if (!data) {
    throw new Error("CSV export is not available for this insight");
  }

  const csv = buildCsv(data.columns, data.rows);
  const blob = new Blob(["\uFEFF", csv], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = insightCsvFilename(card);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
