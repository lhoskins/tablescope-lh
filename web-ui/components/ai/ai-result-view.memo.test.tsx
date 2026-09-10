/**
 * A chart re-rendered with unchanged data must not rebuild the underlying
 * chart object -- otherwise EChartsWidget's effect (keyed on that object's
 * identity) tears down and reinitializes the whole chart on every
 * unrelated parent re-render, e.g. a sibling chat composer's keystroke.
 *
 * Live report: "when typing in chat the charts keep resizing with each key
 * stroke." Reproduced by an un-memoized `buildChart(...)` call directly in
 * ResultChart's render body, so a new chart object -- and downstream a new
 * ECharts dispose+reinit -- was created every render regardless of whether
 * columns/rows/viz actually changed.
 */
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ResultChart } from "./ai-result-view";
import type { InsightChart } from "@/lib/api/home-intelligence";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";

const seenCharts: InsightChart[] = [];

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: ({ chart }: { chart: InsightChart }) => {
    seenCharts.push(chart);
    return <div data-testid="chart-stub" />;
  },
}));

const columns = ["region", "revenue"];
const rows = [
  { region: "North", revenue: 10 },
  { region: "South", revenue: 20 },
];
const viz: SuggestedVisualization = { type: "bar", xField: "region", yField: "revenue" };

function Harness() {
  // Mirrors an unrelated sibling re-render (e.g. a composer's keystroke
  // lifting a re-render of this component's parent) -- columns/rows/viz
  // stay the exact same references across it, only this counter changes.
  const [count, setCount] = useState(0);
  return (
    <div>
      <button onClick={() => setCount((c) => c + 1)}>bump</button>
      <span data-testid="count">{count}</span>
      <ResultChart columns={columns} rows={rows} viz={viz} />
    </div>
  );
}

describe("ResultChart memoization", () => {
  it("does not rebuild the chart object on a re-render with unchanged columns/rows/viz", () => {
    seenCharts.length = 0;
    render(<Harness />);
    expect(screen.getByTestId("chart-stub")).toBeTruthy();
    expect(seenCharts).toHaveLength(1);

    fireEvent.click(screen.getByText("bump"));
    expect(screen.getByTestId("count").textContent).toBe("1");

    // A second render happened (the count updated), but the chart object
    // handed to InsightChartBlock must be the exact same reference -- not
    // just deep-equal -- since EChartsWidget's effect deps compare by
    // reference, not by content.
    expect(seenCharts).toHaveLength(2);
    expect(seenCharts[1]).toBe(seenCharts[0]);
  });
});
