import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const {
  push,
  getInsight,
  suggestInsights,
  createHomePin,
  projectShellProps,
} = vi.hoisted(() => ({
  push: vi.fn(),
  getInsight: vi.fn(),
  suggestInsights: vi.fn(),
  createHomePin: vi.fn().mockResolvedValue({ id: 1 }),
  projectShellProps: { current: {} as Record<string, unknown> },
}));

const INSIGHT = {
  project: { id: 42, name: "Boeing", status: "Active" },
  generatedAt: "2026-06-25T00:00:00Z",
  lastUpdatedAt: "2026-06-25T00:00:00Z",
  executiveSummary: {
    summary: "Project is healthy overall.",
    critical: ["Supplier A SLA breach"],
    warnings: ["Budget variance up"],
    opportunities: ["Consolidate spend"],
    recommendations: ["Renegotiate contract"],
  },
  questionsToAsk: [],
  questionsNeedingData: [],
  aiAvailable: true,
};

const RISK_CARD = {
  id: "risk-1",
  projectId: "42",
  projectName: "Boeing",
  projectColor: "#123456",
  insightType: "risk_sla",
  severity: "critical",
  title: "Delivery lead time exceeds SLA threshold",
  summary: "Average lead time is high.",
  chart: null,
  callout: { type: "risk", text: "Escalate with the supplier." },
  sources: { tables: ["SUP_Quality_CSV"], documents: [] },
  executedAt: "2026-06-25T00:00:00Z",
};

const TREND_CARD = {
  id: "trend-1",
  projectId: "42",
  projectName: "Boeing",
  projectColor: "#123456",
  insightType: "trend_spend",
  severity: "trend",
  title: "Spend is increasing",
  summary: "Monthly spend increased 12%.",
  chart: null,
  callout: null,
  sources: { tables: [], documents: [] },
  executedAt: "2026-06-25T00:00:00Z",
};

const OPPORTUNITY_CARD = {
  id: "opp-1",
  projectId: "42",
  projectName: "Boeing",
  projectColor: "#123456",
  insightType: "opportunity_supplier",
  severity: "recommendation",
  title: "Top-performing suppliers identified",
  summary: "Consolidate with the strongest suppliers.",
  chart: null,
  callout: null,
  sources: { tables: [], documents: [] },
  executedAt: "2026-06-25T00:00:00Z",
};

function suggestionResponse(cards = [RISK_CARD, TREND_CARD, OPPORTUNITY_CARD]) {
  return {
    projects: [
      {
        projectId: "42",
        projectName: "Boeing",
        projectColor: "#123456",
        insights: cards,
      },
    ],
  };
}

vi.mock("@/lib/api/project-insight", () => ({
  projectInsightApi: {
    get: (projectId: string) => getInsight(projectId),
    refresh: (projectId: string) => getInsight(projectId),
    clearCache: () => Promise.resolve(INSIGHT),
  },
}));

vi.mock("@/lib/api/home-intelligence", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/home-intelligence")>()),
  suggestInsights: (granularity?: number, projectId?: number) =>
    suggestInsights(granularity, projectId),
}));

vi.mock("@/lib/api/home-pins", () => ({
  getHomePins: vi.fn().mockResolvedValue([]),
  createHomePin: (payload: unknown) => createHomePin(payload),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: (props: { children: ReactNode } & Record<string, unknown>) => {
    projectShellProps.current = props;
    return <div>{props.children}</div>;
  },
}));

vi.mock("@/lib/hooks/use-insight-feedback", () => ({
  useInsightFeedback: () => ({
    feedbackById: {},
    saveFeedback: vi.fn(),
    removeFeedback: vi.fn(),
    respondToReview: vi.fn(),
    saving: false,
    governanceById: {},
  }),
}));

vi.mock("@/components/tablescope/home/percent-change-summary-panel", () => ({
  PercentChangeSummaryPanel: ({ projectIds }: { projectIds: number[] }) => (
    <div data-testid="percent-change" data-project-ids={projectIds.join(",")} />
  ),
}));

vi.mock("@/components/tablescope/project-actions/create-action-from-insight-dialog", () => ({
  CreateActionFromInsightDialog: ({
    open,
    insight,
  }: {
    open: boolean;
    insight: { title?: string } | null;
  }) =>
    open ? (
      <div role="dialog" aria-label="Create action">
        {insight?.title}
      </div>
    ) : null,
}));

vi.mock("@/components/tablescope/home/save-insight-to-dashboard-modal", () => ({
  SaveInsightToDashboardModal: ({
    open,
    card,
  }: {
    open: boolean;
    card: { title?: string } | null;
  }) =>
    open ? (
      <div role="dialog" aria-label="Save to dashboard">
        {card?.title}
      </div>
    ) : null,
}));

import { ProjectInsightScreen } from "./project-insight-screen";

function renderScreen() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProjectInsightScreen projectId="42" />
    </QueryClientProvider>,
  );
}

function selectTab(name: string) {
  fireEvent.click(screen.getByRole("tab", { name: new RegExp(name, "i") }));
}

describe("ProjectInsightScreen executive layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    projectShellProps.current = {};
    getInsight.mockResolvedValue(INSIGHT);
    suggestInsights.mockResolvedValue(suggestionResponse());
  });

  it("matches the Business Insights executive information architecture", async () => {
    renderScreen();

    expect(
      await screen.findByRole("heading", { name: "Project Insights" }),
    ).toBeTruthy();
    expect(screen.getByText("Executive perspective · AI briefing")).toBeTruthy();
    expect(screen.getByText("Executive brief")).toBeTruthy();
    expect(screen.getByRole("heading", { name: RISK_CARD.title })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Priority insights" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Key developments" })).toBeTruthy();

    for (const tab of [
      "Overview",
      "Risks",
      "Trends",
      "Opportunities",
      "Change summary",
    ]) {
      expect(screen.getByRole("tab", { name: new RegExp(tab, "i") })).toBeTruthy();
    }
    expect(screen.getByLabelText("1 risks")).toBeTruthy();
    expect(screen.getByLabelText("1 trends")).toBeTruthy();
    expect(screen.getByLabelText("1 opportunities")).toBeTruthy();
  });

  it("uses the selected-project Assistant surface and removes resource tabs", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Project Insights" });

    expect(projectShellProps.current.projectId).toBe("42");
    expect(projectShellProps.current.activeNav).toBe("project-insights");
    expect(projectShellProps.current.showResourceTabs).toBe(false);
    expect(projectShellProps.current.assistantSurface).toBe("project_insights");
    expect(projectShellProps.current.assistantContextLabel).toBe("Project Insights");
  });

  it("keeps the brief and developments scoped to the current project", async () => {
    suggestInsights.mockResolvedValue({
      projects: [
        ...suggestionResponse([RISK_CARD]).projects,
        {
          projectId: "99",
          projectName: "Another Project",
          projectColor: "#999999",
          insights: [
            {
              ...RISK_CARD,
              id: "other-risk",
              projectId: "99",
              projectName: "Another Project",
              title: "Other project risk must not appear",
            },
          ],
        },
      ],
    });

    renderScreen();
    expect(
      await screen.findByRole("heading", { name: RISK_CARD.title }),
    ).toBeTruthy();
    expect(screen.queryByText("Other project risk must not appear")).toBeNull();
    expect(suggestInsights).toHaveBeenCalledWith(3, 42);
  });

  it("renders executive cards without changing their actions", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Project Insights" });
    selectTab("Risks");

    const heading = await screen.findByText(RISK_CARD.title);
    const card = heading.closest("article") as HTMLElement;
    expect(within(card).getByText("Critical")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "More Actions" }));
    expect(within(card).getByRole("button", { name: "Explain" })).toBeTruthy();
    expect(
      within(card).getByRole("button", { name: "Add to dashboard" }),
    ).toBeTruthy();
  });

  it("keeps pinning scoped to the selected project", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Project Insights" });
    selectTab("Risks");

    const heading = await screen.findByText(RISK_CARD.title);
    const card = heading.closest("article") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Pin to Home" }));
    await waitFor(() => expect(createHomePin).toHaveBeenCalled());
    expect(createHomePin.mock.calls[0][0]).toEqual(
      expect.objectContaining({ project_id: 42 }),
    );
  });

  it("passes exactly one project to Change Summary", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Project Insights" });
    selectTab("Change summary");

    const panel = await screen.findByTestId("percent-change");
    expect(panel.getAttribute("data-project-ids")).toBe("42");
  });

  it("keeps the Analyze control and last-updated status", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Project Insights" });
    expect(screen.getByText(/Last updated:/)).toBeTruthy();

    let release: (() => void) | undefined;
    getInsight.mockReturnValue(
      new Promise((resolve) => {
        release = () => resolve(INSIGHT);
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Analyze project insights/i }),
    );
    expect(await screen.findByText(/Analyzing this project/)).toBeTruthy();
    release?.();
  });
});
