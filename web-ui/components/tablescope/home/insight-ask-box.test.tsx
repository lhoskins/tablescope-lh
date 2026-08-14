import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { InsightCard, InsightDiagnostic } from "@/lib/api/home-intelligence";
import { cardContext, InsightAskBox } from "./insight-ask-box";

const { askAndRun } = vi.hoisted(() => ({ askAndRun: vi.fn() }));

vi.mock("@/components/dashboard/WidgetRenderer", () => ({
  WidgetRenderer: () => <div data-testid="widget" />,
}));

vi.mock("@/lib/insights/export-png", () => ({
  exportInsightCardPng: vi.fn(),
  insightPngFilename: () => "insight.png",
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useCurrentUser: () => ({ data: undefined }),
}));

vi.mock("@/lib/api/ai-actions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/ai-actions")>();
  return {
    ...actual,
    aiActionsApi: { ...actual.aiActionsApi, askAndRun },
  };
});

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

const STEP: InsightDiagnostic = {
  stage: "quantify",
  title: "Unusual observations",
  question: "Which fall outside the expected range?",
  rationale: "Separates an outlier from noise.",
  finding: "1 observation outside the expected range.",
  sql: "SELECT month, SUM(RevenueUSD) FROM ledger GROUP BY month ORDER BY month",
  analyticalMethod: { method: "detect_anomalies", executionEngine: "r", status: "ok" },
};

function card(overrides: Partial<InsightCard> = {}): InsightCard {
  return {
    id: "c1",
    insightId: "i1",
    projectId: "7",
    projectName: "Ops",
    projectColor: "#000",
    insightType: "trend_spend",
    severity: "trend",
    title: "Rising material costs",
    summary: "Gross margin fell from 30.9% to 24.4%.",
    chart: null,
    callout: null,
    sources: { tables: ["ledger"], documents: [] },
    executedAt: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("cardContext", () => {
  it("carries the card's own query so a follow-up extends those rows", () => {
    const ctx = cardContext(card({ sql: "SELECT * FROM ledger" }));
    expect(ctx.base_sql).toBe("SELECT * FROM ledger");
  });

  it("falls back to a diagnostic's query when the card has none", () => {
    // Method-driven cards carry their evidence on the step, not the card.
    const ctx = cardContext(card({ diagnostics: [STEP] }));
    expect(ctx.base_sql).toBe(STEP.sql);
  });

  it("sends no query rather than a misleading one when neither has SQL", () => {
    expect(cardContext(card()).base_sql).toBeUndefined();
  });

  it("carries the finding's text so the answer stays on this insight", () => {
    const ctx = cardContext(card());
    expect(ctx.title).toBe("Rising material costs");
    expect(ctx.summary).toContain("30.9%");
    expect(ctx.insight_type).toBe("trend_spend");
    expect(ctx.source_tables).toEqual(["ledger"]);
  });

  it("carries method provenance from the card, else from the first step", () => {
    expect(cardContext(card({ diagnostics: [STEP] })).analytical_method?.method).toBe(
      "detect_anomalies",
    );
    const withOwn = cardContext(
      card({
        analyticalMethod: { method: "period_change", executionEngine: "r", status: "ok" },
        diagnostics: [STEP],
      }),
    );
    expect(withOwn.analytical_method?.method).toBe("period_change");
  });
});

describe("InsightAskBox", () => {
  it("renders the matched card's chart and breadcrumb when a live query fails but a card answers it", async () => {
    askAndRun.mockResolvedValueOnce({
      question: "Show me IT backup jobs by system",
      sql: "",
      columns: [],
      rows: [],
      suggestedVisualization: { type: "table" },
      explanation:
        "I couldn't build a live query for this question. I found an existing analysis that answers this: **Backup Jobs by System**",
      dataSourcesUsed: [],
      status: "success",
      answerType: "text",
      error: null,
      matchedInsight: {
        insightId: "backup-001",
        projectId: 7,
        projectName: "IT",
        title: "Backup Jobs by System",
        summary: "Backup job counts grouped by system.",
        chart: { type: "bar", data: { rows: [{ system: "SAP", count: 12 }] } },
        severity: "info",
      },
    });

    renderWithClient(<InsightAskBox card={card()} suggestions={[]} />);

    fireEvent.change(
      screen.getByLabelText("Ask your own question about this insight"),
      { target: { value: "Show me IT backup jobs by system" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(askAndRun).toHaveBeenCalled());
    expect(await screen.findByText("Backup Jobs by System")).toBeInTheDocument();
    expect(screen.getByTestId("widget")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /explore full analysis/i }),
    ).toHaveAttribute("href", "/business-insight/analysis/backup-001");
    // A matched card is a real answer, not a "no rows" result.
    expect(screen.queryByText("That query returned no rows.")).not.toBeInTheDocument();
  });
});
