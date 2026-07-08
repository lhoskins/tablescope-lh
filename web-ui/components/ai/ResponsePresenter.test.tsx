import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ResponseEnvelope } from "@/lib/api/ai-actions";

// The chart renderer pulls in recharts; stub it so the test stays fast.
vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div data-testid="chart" />,
}));

import { ResponsePresenter } from "./ResponsePresenter";

const STRUCTURED: ResponseEnvelope = {
  mode: "structured",
  sections: [
    "summary",
    "chart",
    "grid",
    "show_sql",
    "save_query",
    "create_dashboard",
    "follow_ups",
  ],
  summary: "Defects concentrate in two suppliers.",
  sql: "SELECT supplier, defects FROM q",
  columns: ["supplier", "defects"],
  rows: [{ supplier: "A", defects: 3 }],
  chart: { type: "bar", xField: "supplier", yField: "defects" },
};

describe("ResponsePresenter", () => {
  it("renders sections from the registry order (structured)", () => {
    render(<ResponsePresenter envelope={STRUCTURED} />);
    expect(screen.getByTestId("response-presenter").dataset.mode).toBe(
      "structured",
    );
    expect(
      screen.getByText("Defects concentrate in two suppliers."),
    ).toBeTruthy();
    // Chart + grid render from the shared columns/rows.
    expect(screen.getByTestId("chart")).toBeTruthy();
    expect(screen.getByText("supplier")).toBeTruthy();
    expect(screen.getByText("A")).toBeTruthy();
    // SQL sits behind the Show SQL toggle.
    expect(screen.queryByText(/SELECT supplier/)).toBeNull();
    fireEvent.click(screen.getByText("Show SQL"));
    expect(screen.getByText(/SELECT supplier, defects/)).toBeTruthy();
  });

  it("renders a conversational answer with no chart/grid/SQL", () => {
    const env: ResponseEnvelope = {
      mode: "conversational",
      sections: ["prose_answer", "key_points", "references", "follow_ups"],
      answer: "Late deliveries stem from port congestion.",
      key_points: ["Two carriers drive 80% of delays"],
    };
    render(<ResponsePresenter envelope={env} />);
    expect(
      screen.getByText("Late deliveries stem from port congestion."),
    ).toBeTruthy();
    expect(screen.getByText("Two carriers drive 80% of delays")).toBeTruthy();
    expect(screen.queryByTestId("chart")).toBeNull();
    expect(screen.queryByText(/Show SQL/)).toBeNull();
  });

  it("renders the analytical method block for a hybrid answer", () => {
    const env: ResponseEnvelope = {
      mode: "hybrid",
      sections: [
        "executive_summary",
        "chart",
        "grid",
        "method_envelope",
        "sources",
        "show_sql",
      ],
      executive_summary: "Defect rate differs significantly by supplier.",
      columns: ["supplier", "defects"],
      rows: [{ supplier: "A", defects: 3 }],
      method_envelope: {
        method: "neg_binomial_regression",
        methodName: "Negative Binomial Regression",
        tier: 1,
        n: 42,
        quality: "good",
        caveats: ["Overdispersion detected; counts modeled accordingly"],
      },
      sources: ["quality_inspections_csv"],
      sql: "SELECT supplier, defects FROM q",
    };
    render(<ResponsePresenter envelope={env} />);
    expect(
      screen.getByText(/Analytical method: Negative Binomial Regression/),
    ).toBeTruthy();
    expect(screen.getByText(/n = 42/)).toBeTruthy();
    expect(screen.getByText(/quality_inspections_csv/)).toBeTruthy();
    expect(
      screen.getByText(/Overdispersion detected/),
    ).toBeTruthy();
  });

  it("renders a generated dashboard: narrative + widget chart cards", () => {
    const env: ResponseEnvelope = {
      mode: "dashboard",
      sections: [
        "executive_summary",
        "key_findings",
        "recommended_actions",
        "chart_cards",
        "show_data",
        "save",
      ],
      executive_summary: "Spend is concentrated in a few suppliers.",
      key_findings: ["Top 2 suppliers are 65% of spend"],
      recommended_actions: ["Negotiate volume discounts"],
      chart_cards: [
        {
          title: "Spend by supplier",
          explanation: "Acme and Globex dominate spend.",
          chartType: "bar",
          chart: { type: "bar", data: { series: [{ label: "Acme", value: 1200 }] } },
          sql: "SELECT supplier, spend FROM q",
          labelColumn: "supplier",
          valueColumn: "spend",
        },
      ],
    };
    render(<ResponsePresenter envelope={env} />);
    expect(screen.getByTestId("response-presenter").dataset.mode).toBe(
      "dashboard",
    );
    expect(
      screen.getByText("Spend is concentrated in a few suppliers."),
    ).toBeTruthy();
    expect(screen.getByText("Top 2 suppliers are 65% of spend")).toBeTruthy();
    expect(screen.getByText("Negotiate volume discounts")).toBeTruthy();
    // The widget card renders its title, chart (mocked), and explanation.
    expect(screen.getByText("Spend by supplier")).toBeTruthy();
    expect(screen.getByTestId("chart")).toBeTruthy();
    expect(screen.getByText("Acme and Globex dominate spend.")).toBeTruthy();
    // Show data toggles the widget to a table (chart present -> toggle exists).
    expect(screen.queryByText("1,200")).toBeNull();
    fireEvent.click(screen.getByText("Show data"));
    expect(screen.getByText("1,200")).toBeTruthy();
  });

  it("skips a section whose field is absent", () => {
    const env: ResponseEnvelope = {
      mode: "structured",
      sections: ["summary", "chart", "grid", "show_sql"],
      // no summary, no chart, no sql -> only the grid renders
      columns: ["a"],
      rows: [{ a: 1 }],
    };
    render(<ResponsePresenter envelope={env} />);
    expect(screen.queryByTestId("chart")).toBeNull();
    expect(screen.queryByText(/Show SQL/)).toBeNull();
    expect(screen.getByText("a")).toBeTruthy();
  });
});
