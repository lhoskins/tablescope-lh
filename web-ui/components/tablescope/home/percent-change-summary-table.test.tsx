import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PercentChangeSummaryTable } from "./percent-change-summary-table";
import type {
  PercentChangeSummaryCell,
  PercentChangeSummaryPeriod,
  PercentChangeSummaryRow,
} from "@/lib/api/home-intelligence";

const periods: PercentChangeSummaryPeriod[] = [
  { key: "2025-08", label: "Aug 25", start: "2025-08-01", end: "2025-08-31", is_latest: false },
  { key: "2025-09", label: "Sep 25", start: "2025-09-01", end: "2025-09-30", is_latest: false },
  { key: "2025-10", label: "Oct 25", start: "2025-10-01", end: "2025-10-31", is_latest: true },
  { key: "2025-11", label: "Nov 25", start: "2025-11-01", end: "2025-11-30", is_latest: false },
];

function cell(ratio: number | null, status: PercentChangeSummaryCell["status"]): PercentChangeSummaryCell {
  return {
    current_value: ratio === null ? null : 100,
    previous_value: ratio === null ? null : 50,
    percent_change_ratio: ratio,
    status,
    comparison_status: ratio === null ? "unavailable" : "valid",
    partial: false,
    warnings: [],
  };
}

function row(id: string, title: string, ratios: (number | null)[]): PercentChangeSummaryRow {
  const cells: Record<string, PercentChangeSummaryCell> = {};
  const status: PercentChangeSummaryCell["status"][] = ratios.map((r) =>
    r === null ? "unavailable" : r > 0 ? "positive" : r < 0 ? "negative" : "zero",
  );
  const validRatios = ratios.filter((r): r is number => r !== null);
  const n = validRatios.length;
  periods.forEach((p, i) => {
    cells[p.key] = cell(ratios[i], status[i]);
  });
  return {
    insight_id: id,
    title,
    project_id: 1,
    project_name: "Acme",
    project_color: "#123456",
    priority_score: 0.9,
    source_grain: "month",
    supported_intervals: ["month"],
    data_through: "2025-10-31",
    cells,
    statistics: {
      latest: n > 0 ? validRatios[validRatios.length - 1] : null,
      min: n > 0 ? Math.min(...validRatios) : null,
      max: n > 0 ? Math.max(...validRatios) : null,
      median: n > 0 ? validRatios[Math.floor(n / 2)] : null,
      average: n > 0 ? validRatios.reduce((a, b) => a + b, 0) / n : null,
      standard_deviation: n >= 2 ? 0.1 : null,
      cumulative_change: n > 0 ? 0.5 : null,
      valid_count: n,
    },
  };
}

function renderTable(
  rows: PercentChangeSummaryRow[],
  onSort: (sort: { field: string; direction: "asc" | "desc" }) => void,
) {
  return render(
    <PercentChangeSummaryTable
      periods={periods}
      rows={rows}
      sort={{ field: "latest_absolute_change", direction: "desc" }}
      onSort={onSort}
    />,
  );
}

describe("PercentChangeSummaryTable", () => {
  it("renders full-cell conditional formatting and no direction arrows", () => {
    const rows = [row("r1", "Revenue", [0.05, -0.03, 0.0, null])];
    renderTable(rows, vi.fn());

    const positiveCell = screen.getByLabelText("Positive +5.0%").closest("td");
    expect(positiveCell?.classList.contains("bg-[#74C990]")).toBe(true);
    expect(positiveCell?.classList.contains("text-white")).toBe(true);

    const negativeCell = screen.getByLabelText("Negative -3.0%").closest("td");
    expect(negativeCell?.classList.contains("bg-[#EA7975]")).toBe(true);
    expect(negativeCell?.classList.contains("text-white")).toBe(true);

    const zeroCell = screen.getByLabelText("No change, +0.0%").closest("td");
    expect(zeroCell?.classList.contains("bg-[#626365]")).toBe(true);
    expect(zeroCell?.classList.contains("text-white")).toBe(true);

    const noDataCell = screen.getByLabelText("No data").closest("td");
    expect(noDataCell?.classList.contains("text-ink-tertiary")).toBe(true);

    // No IconArrowUp/IconArrowDown should appear inside body cells.
    const bodyCells = document.querySelectorAll("tbody td");
    bodyCells.forEach((cell) => {
      expect(cell.querySelector("svg")).toBeNull();
    });
  });

  it("announces unavailable cells as No data", () => {
    const rows = [row("r1", "Revenue", [null, null, null, null])];
    renderTable(rows, vi.fn());
    const noDataCells = screen.getAllByLabelText("No data");
    const inBody = Array.from(noDataCells).filter((el) => el.closest("td"));
    expect(inBody.length).toBeGreaterThan(0);
    const noDataCell = inBody[0] as HTMLTableCellElement;
    expect(noDataCell.textContent).toBe("-");
    expect(noDataCell.classList.contains("text-ink-tertiary")).toBe(true);
  });

  it("renders the Period Statistics group after the final period", () => {
    const rows = [row("r1", "Revenue", [0.05, -0.03, 0.0, null])];
    renderTable(rows, vi.fn());
    expect(screen.getByText("Period Statistics")).toBeTruthy();
    ["Latest", "Min", "Max", "Median", "Avg", "Std Dev", "Cumulative", "n"].forEach(
      (label) => {
        expect(screen.getByText(label)).toBeTruthy();
      },
    );
  });

  it("supports sorting by title and statistic columns", () => {
    const onSort = vi.fn();
    const rows = [row("r1", "Revenue", [0.05])];
    renderTable(rows, onSort);

    fireEvent.click(screen.getByRole("button", { name: /Insight/i }));
    expect(onSort).toHaveBeenCalledWith({ field: "title", direction: "asc" });

    fireEvent.click(screen.getByRole("button", { name: /Cumulative/i }));
    expect(onSort).toHaveBeenCalledWith({
      field: "statistics:cumulative_change",
      direction: "desc",
    });
  });

  it("does not render previous/next period paging buttons", () => {
    const rows = [row("r1", "Revenue", [0.05, -0.03, 0.0, null])];
    renderTable(rows, vi.fn());
    expect(screen.queryByRole("button", { name: /Previous periods/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Next periods/i })).toBeNull();
  });
});
