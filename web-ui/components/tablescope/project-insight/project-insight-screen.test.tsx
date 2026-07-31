import { describe, expect, it, vi, beforeEach } from "vitest";
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
  acknowledge,
  reviewed,
  reopen,
  suggestInsights,
  createConversation,
  listConversations,
  submitTurn,
  createHomePin,
} = vi.hoisted(() => ({
  push: vi.fn(),
  getInsight: vi.fn(),
  acknowledge: vi.fn().mockResolvedValue({
    insightId: "i1",
    status: "reviewed",
    acknowledgedByUserId: 1,
    acknowledgedByName: "Leonard",
    acknowledgedAt: "2026-06-25T00:00:00Z",
  }),
  reviewed: vi.fn().mockResolvedValue({ items: [] }),
  reopen: vi.fn().mockResolvedValue({ insightId: "i1", status: "reopened" }),
  suggestInsights: vi.fn(),
  createConversation: vi.fn(),
  listConversations: vi.fn().mockResolvedValue([]),
  submitTurn: vi.fn(),
  createHomePin: vi.fn().mockResolvedValue({ id: 1 }),
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
  questionsToAsk: [
    { id: "q1", question: "Why did Supplier A slip?", reason: "risk" },
  ],
  questionsNeedingData: [],
  aiAvailable: true,
};

vi.mock("@/lib/api/project-insight", () => ({
  projectInsightApi: {
    get: (projectId: string) => getInsight(projectId),
    refresh: (projectId: string) => getInsight(projectId),
    acknowledge: (projectId: string, insightId: string) =>
      acknowledge(projectId, insightId),
    reviewed: (projectId: string) => reviewed(projectId),
    reopen: (projectId: string, insightId: string) =>
      reopen(projectId, insightId),
    clearCache: () =>
      Promise.resolve({
        deleted: { project_intelligence_snapshots: 1, business_insight_results: 0 },
      }),
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

vi.mock("@/lib/api/conversational-analytics", () => ({
  createConversation: (payload: unknown) => createConversation(payload),
  listConversations: (projectId?: number) => listConversations(projectId),
  submitTurn: (conversationId: number, payload: unknown) =>
    submitTurn(conversationId, payload),
  getConversation: vi.fn().mockResolvedValue({ id: 1, turns: [] }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useCurrentUser: () => ({
    data: { user: { rawRole: "admin" }, tenant: {} },
  }),
  useProjectSummaries: () => ({ data: [] }),
}));

vi.mock("@/lib/hooks/use-insight-feedback", () => ({
  useInsightFeedback: () => ({
    feedbackById: {},
    isLoading: false,
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

function expandSection(name: string) {
  fireEvent.click(
    screen.getByRole("button", { name: new RegExp(`^${name}(?: \\d+)?$`) }),
  );
}

function expandCardActions(card: HTMLElement) {
  fireEvent.click(within(card).getByRole("button", { name: /More Actions/i }));
}

describe("ProjectInsightScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reviewed.mockReset();
    reviewed.mockResolvedValue({ items: [] });
    getInsight.mockReset();
    getInsight.mockResolvedValue(INSIGHT);
    suggestInsights.mockReset();
    suggestInsights.mockResolvedValue({ projects: [] });
  });

  it("renders the Business-Insight-style layout sections", async () => {
    renderScreen();
    expect(
      await screen.findByRole("heading", { name: "Executive Project Summary" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Risks" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Trends" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Opportunities" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Deeper analysis" })).toBeTruthy();
  });

  it("does not render legacy panels", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expect(screen.queryByText("Trend Detection")).toBeNull();
    expect(screen.queryByText("What Changed Since Last Visit")).toBeNull();
    expect(screen.queryByText("Insight Validation Workflow")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Insights & Opportunities \d*$/ })).toBeNull();
  });

  it("renders executive summary as tinted, colored cards", async () => {
    const { container } = renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expect(screen.getByText("Critical")).toBeTruthy();
    expect(screen.getByText("Warnings")).toBeTruthy();
    expect(screen.getByText("Supplier A SLA breach")).toBeTruthy();
    expect(container.querySelector('[class*="bg-danger/5"]')).toBeTruthy();
  });

  it("keeps all sections collapsed by default", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    for (const name of ["Risks", "Trends", "Opportunities", "Deeper analysis"]) {
      expect(
        screen.getByRole("button", { name }).getAttribute("aria-expanded"),
      ).toBe("false");
    }
  });

  it("shows AI-generated questions inside Deeper analysis after expanding", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expect(screen.queryByText("Why did Supplier A slip?")).toBeNull();
    expandSection("Deeper analysis");
    expect(
      await screen.findByText("Why did Supplier A slip?"),
    ).toBeTruthy();
  });

  it("derives cards from project-scoped AI suggestions", async () => {
    suggestInsights.mockResolvedValue({
      projects: [
        {
          projectId: "42",
          projectName: "Boeing",
          projectColor: "#123456",
          insights: [
            {
              id: "trend-1",
              projectId: "42",
              projectName: "Boeing",
              projectColor: "#123456",
              insightType: "trend_spend",
              severity: "trend",
              title: "Spend up",
              summary: "MoM +12%",
              chart: null,
              callout: null,
              sources: { tables: [], documents: [] },
              executedAt: "2026-06-25T00:00:00Z",
            },
          ],
        },
      ],
    });
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expandSection("Trends");
    expect(await screen.findByText("Spend up")).toBeTruthy();
    expect(screen.getByText("Trend")).toBeTruthy();
    await waitFor(() => expect(suggestInsights).toHaveBeenCalledWith(3, 42));
  });

  it("shows unanswerable questions inside Deeper analysis", async () => {
    getInsight.mockResolvedValue({
      ...INSIGHT,
      questionsNeedingData: [
        {
          id: "nd1",
          question: "What is employee headcount by department?",
          missingDataHint: "Add a source with the relevant data to enable it.",
        },
      ],
    });
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expandSection("Deeper analysis");
    expect(await screen.findByText("Needs additional data")).toBeTruthy();
    expect(
      screen.getByText("What is employee headcount by department?"),
    ).toBeTruthy();
    expect(
      screen.getByText("Add a source with the relevant data to enable it."),
    ).toBeTruthy();
  });

  it("does not render the legacy inline Ask box", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expect(
      screen.queryByLabelText("Ask a question about this project"),
    ).toBeNull();
  });

  it("creates a project-scoped Ask Anything conversation with the right title", async () => {
    createConversation.mockResolvedValue({
      id: 7,
      project_id: 42,
      title: "Project Insights",
      turns: [
        {
          id: 1,
          user_message: "Why did Supplier A slip?",
          assistant_message: "Because of a lead-time issue.",
          status: "success",
        },
      ],
    });
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    const input = screen.getByLabelText(
      "Ask anything across your connected data, documents, and dashboards",
    );
    fireEvent.change(input, { target: { value: "Why did Supplier A slip?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() =>
      expect(createConversation).toHaveBeenCalledWith(
        expect.objectContaining({
          project_id: 42,
          title: "Project Insights",
          initial_message: "Why did Supplier A slip?",
        }),
      ),
    );
  });

  it("renders AI-derived risk/opportunity cards with severity badges and actions", async () => {
    suggestInsights.mockResolvedValue({
      projects: [
        {
          projectId: "42",
          projectName: "Boeing",
          projectColor: "#123456",
          insights: [
            {
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
            },
            {
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
            },
          ],
        },
      ],
    });
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expandSection("Risks");
    const heading = await screen.findByText(
      "Delivery lead time exceeds SLA threshold",
    );
    const card = heading.closest("article") as HTMLElement;
    expect(within(card).getByText("Critical")).toBeTruthy();
    expandCardActions(card);
    expect(within(card).getByRole("button", { name: "Explain" })).toBeTruthy();
    expect(
      within(card).getByRole("button", { name: "Add to dashboard" }),
    ).toBeTruthy();
    expandSection("Opportunities");
    const oppHeading = await screen.findByText(
      "Top-performing suppliers identified",
    );
    const oppCard = oppHeading.closest("article") as HTMLElement;
    expect(within(oppCard).getByText("Recommendation")).toBeTruthy();
  });

  it("pins a card to Home", async () => {
    suggestInsights.mockResolvedValue({
      projects: [
        {
          projectId: "42",
          projectName: "Boeing",
          projectColor: "#123456",
          insights: [
            {
              id: "risk-1",
              projectId: "42",
              projectName: "Boeing",
              projectColor: "#123456",
              insightType: "risk_sla",
              severity: "critical",
              title: "Delivery lead time exceeds SLA threshold",
              summary: "Average lead time is high.",
              chart: null,
              callout: null,
              sources: { tables: [], documents: [] },
              executedAt: "2026-06-25T00:00:00Z",
            },
          ],
        },
      ],
    });
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expandSection("Risks");
    const heading = await screen.findByText(
      "Delivery lead time exceeds SLA threshold",
    );
    const card = heading.closest("article") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Pin to Home" }));
    await waitFor(() => expect(createHomePin).toHaveBeenCalled());
    const payload = createHomePin.mock.calls[0][0] as { project_id: number };
    expect(payload.project_id).toBe(42);
  });

  it("passes a single project id to Percent Change Summary", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    const panel = await screen.findByTestId("percent-change");
    expect(panel.getAttribute("data-project-ids")).toBe("42");
  });

  it("shows a last-updated timestamp and analyzing status on refresh", async () => {
    renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expect(screen.getByText(/Last updated:/)).toBeTruthy();
    let release: (() => void) | undefined;
    getInsight.mockReturnValue(
      new Promise((resolve) => {
        release = () => resolve(INSIGHT);
      }),
    );
    const refresh = screen.getByRole("button", {
      name: /Refresh project insights/i,
    });
    fireEvent.click(refresh);
    expect(await screen.findByText(/Analyzing this project/)).toBeTruthy();
    release?.();
  });

  it("has no residual card shadows in the page body", async () => {
    const { container } = renderScreen();
    await screen.findByRole("heading", { name: "Executive Project Summary" });
    expect(container.querySelector('article [class*="shadow"]')).toBeNull();
  });
});
