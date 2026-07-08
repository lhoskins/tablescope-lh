import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { generateProjectDashboard, saveDashboardSuggestion } = vi.hoisted(() => ({
  generateProjectDashboard: vi.fn(),
  saveDashboardSuggestion: vi.fn(),
}));

vi.mock("@/lib/api/home-intelligence", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("@/lib/api/home-intelligence")
  >();
  return { ...actual, generateProjectDashboard, saveDashboardSuggestion };
});

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div data-testid="chart-block" />,
}));

import { GenerateDashboardModal } from "./generate-dashboard-modal";

const DASHBOARD = {
  projectId: "42",
  projectName: "Boeing",
  projectColor: "#123456",
  dashboard: {
    title: "Boeing — AI Dashboard",
    summary: "Supplier performance overview across 3 charts.",
    keyFindings: ["Supplier A leads on defect rate at 4.2%"],
    recommendedActions: ["Review Supplier A quality plan"],
    widgets: [
      {
        title: "Defect rate by supplier",
        subtitle: "",
        explanation: "Supplier A leads on defect rate at 4.2% across 5 items.",
        format: "percent",
        chartType: "horizontal_bar",
        sql: "SELECT ...",
        labelColumn: "supplier",
        valueColumn: "defect_rate",
        chart: {
          type: "bar",
          title: "Defect rate by supplier",
          data: {
            series: [
              { label: "Supplier A", value: 0.042 },
              { label: "Supplier B", value: 0.031 },
            ],
          },
        },
      },
    ],
  },
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("GenerateDashboardModal readability layer", () => {
  it("renders the executive summary, findings, actions and per-chart explanation", async () => {
    generateProjectDashboard.mockResolvedValue(DASHBOARD);
    render(
      <GenerateDashboardModal
        open
        projectId="42"
        onClose={() => {}}
        onSaved={() => {}}
        notify={() => {}}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Supplier performance overview/i),
      ).toBeTruthy(),
    );
    expect(screen.getByText(/Key findings/i)).toBeTruthy();
    expect(screen.getByText(/Recommended actions/i)).toBeTruthy();
    expect(
      screen.getByText(/Supplier A leads on defect rate at 4.2% across 5 items/),
    ).toBeTruthy();
  });

  it("toggles Show data and formats percent values", async () => {
    generateProjectDashboard.mockResolvedValue(DASHBOARD);
    render(
      <GenerateDashboardModal
        open
        projectId="42"
        onClose={() => {}}
        onSaved={() => {}}
        notify={() => {}}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.getByText(/Show data/i)).toBeTruthy());
    fireEvent.click(screen.getByText(/Show data/i));
    expect(screen.getByText("4.2%")).toBeTruthy();
    expect(screen.getByText("3.1%")).toBeTruthy();
  });
});
