import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { IntelligenceFeed } from "./intelligence-feed";
import type { InsightCard } from "@/lib/api/home-intelligence";

const { streamHomeIntelligence, getIntelligenceSnapshot, getPreferences, updatePreferences } = vi.hoisted(() => ({
  streamHomeIntelligence: vi.fn(() => ({ abort: vi.fn() })),
  getIntelligenceSnapshot: vi.fn(),
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
}));

vi.mock("@/lib/api/home-intelligence", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/home-intelligence")>()),
  streamHomeIntelligence,
  getIntelligenceSnapshot,
  getPreferences,
  updatePreferences,
}));

vi.mock("@/lib/api/insight-feedback", () => ({
  batchGetInsightFeedback: vi.fn().mockResolvedValue({ items: [] }),
}));

const RISK: InsightCard = {
  id: "risk-1",
  projectId: "1",
  projectName: "Project A",
  projectColor: "#123456",
  insightType: "risk_sla",
  severity: "critical",
  title: "SLA breach",
  summary: "Supplier missed SLA.",
  chart: null,
  callout: null,
  sources: { tables: [], documents: [] },
  executedAt: "2026-01-01T00:00:00Z",
};

const TREND: InsightCard = {
  ...RISK,
  id: "trend-1",
  insightType: "trend_spend",
  severity: "watch",
  title: "Spend trending up",
  summary: "Monthly spend increased.",
};

const OPPORTUNITY: InsightCard = {
  ...RISK,
  id: "opp-1",
  insightType: "opportunity_supplier",
  severity: "opportunity",
  title: "Consolidate suppliers",
  summary: "Top suppliers account for most spend.",
};

const SNAPSHOT = {
  granularity: 3,
  updatedAt: "2026-01-01T00:00:00Z",
  generatedAt: "2026-01-01T00:00:00Z",
  projects: [{ id: "1", name: "Project A", color: "#123456" }],
  results: [
    {
      projectId: "1",
      projectName: "Project A",
      projectColor: "#123456",
      insights: [RISK, TREND, OPPORTUNITY],
    },
  ],
  synthesis: null,
};

function renderFeed() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <IntelligenceFeed />
    </QueryClientProvider>,
  );
}

describe("IntelligenceFeed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getPreferences.mockResolvedValue({
      intelligence: {
        run_on_load: false,
        cross_project: true,
        email_digest: false,
        granularity: 3,
      },
    });
    getIntelligenceSnapshot.mockResolvedValue({ snapshot: SNAPSHOT });
  });

  it("renders collapsible Risks, Trends, and Opportunities sections", async () => {
    renderFeed();
    expect(await screen.findByRole("button", { name: /Risks/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Trends/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Opportunities/ })).toBeTruthy();
  });

  it("starts with Risks, Trends, and Opportunities collapsed", async () => {
    renderFeed();
    const risks = await screen.findByRole("button", { name: /Risks/ });
    const trends = screen.getByRole("button", { name: /Trends/ });
    const opportunities = screen.getByRole("button", { name: /Opportunities/ });

    expect(risks.getAttribute("aria-expanded")).toBe("false");
    expect(trends.getAttribute("aria-expanded")).toBe("false");
    expect(opportunities.getAttribute("aria-expanded")).toBe("false");

    expect(screen.queryByText("SLA breach")).toBeNull();
    expect(screen.queryByText("Spend trending up")).toBeNull();
    expect(screen.queryByText("Consolidate suppliers")).toBeNull();
  });

  it("expands and re-collapses Risks independently", async () => {
    renderFeed();
    const risks = await screen.findByRole("button", { name: /Risks/ });
    expect(risks.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("SLA breach")).toBeNull();

    fireEvent.click(risks);
    expect(await screen.findByText("SLA breach")).toBeTruthy();
    expect(risks.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(risks);
    await waitFor(() => expect(screen.queryByText("SLA breach")).toBeNull());
    expect(risks.getAttribute("aria-expanded")).toBe("false");
  });

  it("expanding one section does not expand the others", async () => {
    renderFeed();
    const risks = await screen.findByRole("button", { name: /Risks/ });
    const trends = screen.getByRole("button", { name: /Trends/ });
    const opportunities = screen.getByRole("button", { name: /Opportunities/ });

    fireEvent.click(risks);
    expect(await screen.findByText("SLA breach")).toBeTruthy();
    expect(risks.getAttribute("aria-expanded")).toBe("true");
    expect(trends.getAttribute("aria-expanded")).toBe("false");
    expect(opportunities.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(trends);
    expect(await screen.findByText("Spend trending up")).toBeTruthy();
    expect(trends.getAttribute("aria-expanded")).toBe("true");
    expect(opportunities.getAttribute("aria-expanded")).toBe("false");
  });

  it("renders analytical method metadata behind the Explain panel on chart cards", async () => {
    const chartCard: InsightCard = {
      ...TREND,
      id: "trend-method",
      title: "Spend concentrated",
      summary: "Spend is concentrated among top suppliers.",
      chart: {
        type: "bar",
        title: "Spend by supplier",
        data: {
          series: [
            { label: "Acme", value: 1200 },
            { label: "Globex", value: 800 },
          ],
        },
      },
      analyticalMethod: {
        method: "pareto_analysis",
        methodName: "Pareto analysis",
        status: "ok",
        quality: "reliable",
        tier: 1,
        n: 10,
        usableN: 10,
        results: { topPercent: 80 },
        assumptions: ["Independent categories"],
        warnings: [],
        caveats: [],
      },
    };
    getIntelligenceSnapshot.mockResolvedValue({
      snapshot: {
        ...SNAPSHOT,
        results: [
          {
            ...SNAPSHOT.results[0],
            insights: [chartCard],
          },
        ],
      },
    });
    renderFeed();
    fireEvent.click(screen.getByRole("button", { name: /Trends/ }));
    await screen.findByText("Spend concentrated");
    fireEvent.click(screen.getByRole("button", { name: /Explain/i }));
    expect(await screen.findByText("Analytical method: Pareto analysis")).toBeTruthy();
    expect(screen.getByText("Quality: reliable")).toBeTruthy();
  });

  it("does not re-request intelligence on toggle", async () => {
    renderFeed();
    await screen.findByRole("button", { name: /Risks/ });
    const before = streamHomeIntelligence.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: /Trends/ }));
    expect(streamHomeIntelligence.mock.calls.length).toBe(before);

    fireEvent.click(screen.getByRole("button", { name: /Opportunities/ }));
    expect(streamHomeIntelligence.mock.calls.length).toBe(before);
  });
});
