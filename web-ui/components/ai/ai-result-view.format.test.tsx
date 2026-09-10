/**
 * Live report: a SuccessRate/FailureRate column in an AI Assistant chat
 * result table showed raw floating-point precision straight from SQL
 * (0.9166666666666666) instead of a readable rate. Table cells and KPI
 * values were stringified from the raw row value with no formatting at
 * all -- this covers the fix, rounding non-integer numbers to 2 decimal
 * places while leaving integers and non-numeric values untouched.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { buildChart, ResultTable } from "./ai-result-view";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";

describe("ResultTable number formatting", () => {
  it("rounds a non-integer numeric cell to 2 decimal places", () => {
    render(
      <ResultTable
        columns={["System", "SuccessRate"]}
        rows={[{ System: "PLM", SuccessRate: 0.9166666666666666 }]}
      />,
    );
    expect(screen.getByText("0.92")).toBeTruthy();
    expect(screen.queryByText("0.9166666666666666")).toBeNull();
  });

  it("leaves an integer cell as a plain integer, no trailing .00", () => {
    render(
      <ResultTable
        columns={["System", "JobCount"]}
        rows={[{ System: "PLM", JobCount: 12 }]}
      />,
    );
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.queryByText("12.00")).toBeNull();
  });

  it("rounds a numeric value even when it arrives as a string", () => {
    render(
      <ResultTable
        columns={["FailureRate"]}
        rows={[{ FailureRate: "0.08333333333333333" }]}
      />,
    );
    expect(screen.getByText("0.08")).toBeTruthy();
  });

  it("leaves non-numeric text untouched", () => {
    render(
      <ResultTable columns={["System"]} rows={[{ System: "FileServer" }]} />,
    );
    expect(screen.getByText("FileServer")).toBeTruthy();
  });
});

describe("buildChart KPI value formatting", () => {
  it("rounds a non-integer KPI value to 2 decimal places", () => {
    const chart = buildChart(
      ["SuccessRate"],
      [{ SuccessRate: 0.7777777777777778 }],
      { type: "kpi", metricField: "SuccessRate" } as SuggestedVisualization,
    );
    expect(chart?.data.kpis?.[0]?.value).toBe("0.78");
  });

  it("leaves an integer KPI value unrounded", () => {
    const chart = buildChart(
      ["JobCount"],
      [{ JobCount: 50 }],
      { type: "kpi", metricField: "JobCount" } as SuggestedVisualization,
    );
    expect(chart?.data.kpis?.[0]?.value).toBe("50");
  });
});
