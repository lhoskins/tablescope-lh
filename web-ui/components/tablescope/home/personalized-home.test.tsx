import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const {
  getHomeActionSummary,
  getIntelligenceSnapshot,
  getPreferences,
  updatePreferences,
  useAllDocuments,
} = vi.hoisted(() => ({
  getHomeActionSummary: vi.fn(),
  getIntelligenceSnapshot: vi.fn(),
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  useAllDocuments: vi.fn(),
}));

const { chartMock, initMock, useMock } = vi.hoisted(() => {
  const chartMock = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
  const initMock = vi.fn(() => chartMock);
  const useMock = vi.fn();
  return { chartMock, initMock, useMock };
});

vi.mock("@/lib/api/home-actions", () => ({ getHomeActionSummary }));
vi.mock("@/lib/api/home-intelligence", () => ({
  getIntelligenceSnapshot,
  getPreferences,
  updatePreferences,
}));
vi.mock("@/lib/ui/use-shell-data", () => ({ useAllDocuments }));
vi.mock("echarts/core", () => ({ use: useMock, init: initMock }));

import { PersonalizedHome } from "./personalized-home";

const BASE_SUMMARY = {
  highlights: { needs_attention: 2, due_this_week: 3, recently_completed: 1 },
  assigned: [
    {
      id: 1,
      project_id: 9,
      project_name: "Sales Operations",
      title: "Approve backlog recovery milestones",
      status: "in_progress",
      priority: "high",
      percent_complete: 40,
      due_date: null,
      completed_at: null,
      updated_at: "2026-08-20T00:00:00Z",
    },
  ],
  updates: [],
  updates_matched_focus: false,
};

const BASE_PREFERENCES = {
  intelligence: {
    run_on_load: false,
    cross_project: true,
    email_digest: false,
    granularity: 2,
    home_focus: ["Revenue vs backlog", "ITSM SLA risk"],
    home_persona: "ceo",
  },
};

const REVENUE_INSIGHT = {
  id: "revenue-1",
  insightId: "revenue-1",
  projectId: "9",
  projectName: "Sales Operations",
  projectColor: "#2563eb",
  insightType: "trend",
  severity: "warning",
  title: "Revenue conversion softened while backlog remained elevated",
  summary: "Revenue conversion is below the plan while open backlog remains elevated.",
  chart: {
    type: "line",
    title: "Revenue and backlog trend",
    data: { series: [{ label: "Jul", value: 42 }] },
  },
  callout: null,
  sources: { tables: ["sales_monthly"], documents: [] },
  executedAt: "2026-08-22T00:00:00Z",
  priorityScore: 92,
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PersonalizedHome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getHomeActionSummary.mockResolvedValue(BASE_SUMMARY);
    getPreferences.mockResolvedValue(BASE_PREFERENCES);
    updatePreferences.mockResolvedValue(BASE_PREFERENCES);
    getIntelligenceSnapshot.mockResolvedValue({
      snapshot: {
        granularity: 2,
        updatedAt: "2026-08-22T00:00:00Z",
        projects: [],
        results: [
          {
            projectId: "9",
            projectName: "Sales Operations",
            projectColor: "#2563eb",
            insights: [REVENUE_INSIGHT],
          },
        ],
        synthesis: null,
      },
    });
    useAllDocuments.mockReturnValue({
      data: [
        {
          id: 44,
          name: "Q3 Performance Review",
          projectId: 9,
          projectName: "Sales Operations",
          aiStatus: "profiled",
          sharedBy: "Leonard",
          ownerId: 1,
          ownerName: "Leonard",
          createdAt: "2026-08-20T00:00:00Z",
          updatedAt: "2026-08-21T00:00:00Z",
          aiSummary: "The performance review identifies margin and forecast pressure.",
        },
      ],
      isLoading: false,
    });
  });

  it("renders the persona briefing, light metrics, chart, and mixed key developments", async () => {
    render(
      <PersonalizedHome projectCount={4} greetingText="Good morning, Leonard" />,
      { wrapper },
    );

    await waitFor(() => expect(initMock).toHaveBeenCalled());
    expect(screen.getByText("CEO perspective · Personal business briefing")).toBeTruthy();
    expect(screen.getByText("Projects monitored")).toBeTruthy();
    expect(screen.getByText("Company performance")).toBeTruthy();
    expect(screen.getByText("Q3 Performance Review")).toBeTruthy();
    expect(
      screen.getAllByText("Revenue conversion softened while backlog remained elevated").length,
    ).toBeGreaterThan(0);
  });

  it("moves persona and focus controls into Home settings and saves both", async () => {
    render(
      <PersonalizedHome projectCount={4} greetingText="Good morning, Leonard" />,
      { wrapper },
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "CEO view" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "CEO view" }));

    expect(screen.getByRole("dialog", { name: "Home settings" })).toBeTruthy();
    expect(screen.getByText("Revenue vs backlog")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Persona"), {
      target: { value: "business_analyst" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() =>
      expect(updatePreferences).toHaveBeenCalledWith({
        home_persona: "business_analyst",
        home_focus: ["Revenue vs backlog", "ITSM SLA risk"],
      }),
    );
  });
});
