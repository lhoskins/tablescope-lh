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

  it("starts with sections expanded", async () => {
    renderFeed();
    const risks = await screen.findByRole("button", { name: /Risks/ });
    expect(risks.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("SLA breach")).toBeTruthy();
    expect(screen.getByText("Spend trending up")).toBeTruthy();
    expect(screen.getByText("Consolidate suppliers")).toBeTruthy();
  });

  it("collapses and re-expands Risks independently", async () => {
    renderFeed();
    const risks = await screen.findByRole("button", { name: /Risks/ });
    expect(screen.getByText("SLA breach")).toBeTruthy();

    fireEvent.click(risks);
    await waitFor(() => expect(screen.queryByText("SLA breach")).toBeNull());
    expect(risks.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(risks);
    await waitFor(() =>
      expect(screen.getByText("SLA breach")).toBeTruthy(),
    );
    expect(risks.getAttribute("aria-expanded")).toBe("true");
  });

  it("collapsing Risks does not collapse Trends or Opportunities", async () => {
    renderFeed();
    const risks = await screen.findByRole("button", { name: /Risks/ });
    const trends = screen.getByRole("button", { name: /Trends/ });
    const opportunities = screen.getByRole("button", { name: /Opportunities/ });

    fireEvent.click(risks);
    await waitFor(() => expect(screen.queryByText("SLA breach")).toBeNull());

    expect(screen.getByText("Spend trending up")).toBeTruthy();
    expect(screen.getByText("Consolidate suppliers")).toBeTruthy();
    expect(trends.getAttribute("aria-expanded")).toBe("true");
    expect(opportunities.getAttribute("aria-expanded")).toBe("true");
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
