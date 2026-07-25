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

const { push, getInsight, acknowledge, reviewed, reopen, suggestInsights } =
  vi.hoisted(() => ({
    push: vi.fn(),
    getInsight: vi.fn(),
    suggestInsights: vi.fn(),
    acknowledge: vi.fn().mockResolvedValue({
      insightId: "i1",
      status: "reviewed",
      acknowledgedByUserId: 1,
      acknowledgedByName: "Leonard",
      acknowledgedAt: "2026-06-25T00:00:00Z",
    }),
    reviewed: vi.fn().mockResolvedValue({ items: [] }),
    reopen: vi.fn().mockResolvedValue({ insightId: "i1", status: "reopened" }),
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
  trendDetection: [
    {
      id: "t1",
      label: "Spend up",
      description: "MoM +12%",
      possibleCause: "New supplier onboarding",
    },
  ],
  recommendedDashboards: [
    { id: "d1", title: "Supplier SLA", status: "suggested" },
  ],
  recommendedQueries: [
    { id: "rq1", title: "Late shipments", status: "suggested" },
  ],
  recommendedKpis: [
    { id: "k1", name: "On-time %", status: "recommended", currentValue: null },
  ],
  whatChangedSinceLastVisit: {
    newFilesAdded: 2,
    changedDataSources: 1,
    newRisksIdentified: 0,
    newQueries: 3,
    newDashboards: 1,
    updatedKnowledgeGraph: 4,
    changeLogLink: "/projects/42/audit-log",
  },
  insightValidationWorkflow: [
    { id: "i1", title: "Supplier A risk", priority: "high", status: "new" },
  ],
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
  },
}));

vi.mock("@/lib/api/home-intelligence", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/home-intelligence")>()),
  suggestInsights: (granularity?: number, projectId?: number) =>
    suggestInsights(granularity, projectId),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/ai/AIQuestionResultModal", () => ({
  AIQuestionResultModal: ({
    open,
    question,
  }: {
    open: boolean;
    question: string;
  }) =>
    open ? (
      <div role="dialog" aria-label="AI Answer">
        {question}
      </div>
    ) : null,
}));

vi.mock("@/components/ai/GenerateQueryPreviewModal", () => ({
  GenerateQueryPreviewModal: ({
    open,
    question,
    title,
  }: {
    open: boolean;
    question: string;
    title?: string;
  }) =>
    open ? (
      <div role="dialog" aria-label="Generate Query">
        {title || question}
      </div>
    ) : null,
}));

vi.mock("@/components/tablescope/project-insight/generate-dashboard-modal", () => ({
  GenerateDashboardModal: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="Generate Dashboard" /> : null,
}));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({
    children,
    actions,
  }: {
    children: ReactNode;
    actions?: ReactNode;
  }) => (
    <div>
      <div data-testid="actions">{actions}</div>
      {children}
    </div>
  ),
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useCurrentUser: () => ({
    data: {
      user: { rawRole: "admin" },
      tenant: {},
    },
  }),
  useProjectSummaries: () => ({ data: [] }),
}));

vi.mock("@/lib/hooks/use-insight-feedback", () => ({
  useInsightFeedback: () => ({
    feedbackById: {},
    isLoading: false,
    saveFeedback: vi.fn(),
    removeFeedback: vi.fn(),
    saving: false,
  }),
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

/** Expand a collapsible Panel by clicking its section header (the click
 * bubbles from the heading up to the header's role="button" handler). */
function expandSection(name: string | RegExp) {
  fireEvent.click(screen.getByRole("heading", { name }));
}

describe("ProjectInsightScreen", () => {
  beforeEach(() => {
    push.mockClear();
    acknowledge.mockClear();
    reopen.mockClear();
    reviewed.mockReset();
    reviewed.mockResolvedValue({ items: [] });
    getInsight.mockReset();
    getInsight.mockResolvedValue(INSIGHT);
    suggestInsights.mockReset();
    suggestInsights.mockResolvedValue({ projects: [] });
  });

  it("renders the restyled layout sections", async () => {
    renderScreen();
    expect(
      await screen.findByText("Executive Project Summary"),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Risks" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Trends" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Insights & Opportunities" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "AI-Generated Questions to Ask" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Recommendations"),
    ).toBeTruthy();
  });

  it("removes the panels that are not part of the restyle", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");
    expect(screen.queryByText("Trend Detection")).toBeNull();
    expect(screen.queryByText("What Changed Since Last Visit")).toBeNull();
    expect(screen.queryByText("Insight Validation Workflow")).toBeNull();
  });

  it("renders executive summary as tinted, colored cards", async () => {
    const { container } = renderScreen();
    expect(await screen.findByText("Critical")).toBeTruthy();
    expect(screen.getByText("Warnings")).toBeTruthy();
    expect(screen.getAllByText("Opportunities").length).toBeGreaterThan(0);
    expect(screen.getByText("Supplier A SLA breach")).toBeTruthy();
    // The Critical card is a tinted danger box.
    expect(container.querySelector('[class*="bg-danger/5"]')).toBeTruthy();
  });

  it("expands Insights & Opportunities and collapses Questions by default", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");

    const insights = screen.getByRole("heading", {
      name: /Insights & Opportunities/,
    });
    expect(insights.closest("section")?.firstElementChild?.getAttribute("aria-expanded")).toBe("true");

    const questions = screen.getByRole("heading", {
      name: /AI-Generated Questions to Ask/,
    });
    expect(questions.closest("section")?.firstElementChild?.getAttribute("aria-expanded")).toBe("false");
    // Count badge (1 question) is shown while collapsed.
    expect(within(questions.closest("section") as HTMLElement).getByText("1")).toBeTruthy();
    // Collapsed content is absent.
    expect(screen.queryByText("Why did Supplier A slip?")).toBeNull();
  });

  it("expands a collapsed section when its header is clicked", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");
    expect(screen.queryByText("Why did Supplier A slip?")).toBeNull();
    expandSection("AI-Generated Questions to Ask");
    expect(
      await screen.findByText("Why did Supplier A slip?"),
    ).toBeTruthy();
  });

  it("derives trend cards from the shared AI insight backend", async () => {
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
    await screen.findByText("Executive Project Summary");
    // The former Trend Detection panel is gone; trends come from AI insights.
    expect(screen.queryByText("Trend Detection")).toBeNull();
    expect((await screen.findAllByText("Spend up")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Trend").length).toBeGreaterThan(0);
  });

  it("shows unanswerable questions after expanding the Questions section", async () => {
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
    await screen.findByText("Executive Project Summary");
    expandSection("AI-Generated Questions to Ask");
    expect(await screen.findByText("Needs additional data")).toBeTruthy();
    expect(
      screen.getByText("What is employee headcount by department?"),
    ).toBeTruthy();
    expect(
      screen.getByText("Add a source with the relevant data to enable it."),
    ).toBeTruthy();
  });

  it("shows suggestion status for executive summary cards", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");
    expect(screen.getByText("Supplier A SLA breach")).toBeTruthy();
    expect(screen.getByText("Consolidate spend")).toBeTruthy();
    expect(screen.getByText("Renegotiate contract")).toBeTruthy();
  });

  it("does not render the legacy inline Ask box", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");
    expect(
      screen.queryByLabelText("Ask a question about this project"),
    ).toBeNull();
  });

  it("opens the AI answer modal when a suggested question is clicked", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");
    expandSection("AI-Generated Questions to Ask");
    const q = await screen.findByText("Why did Supplier A slip?");
    fireEvent.click(q);
    const dialog = await screen.findByRole("dialog", { name: "AI Answer" });
    expect(dialog.textContent).toContain("Why did Supplier A slip?");
    expect(push).not.toHaveBeenCalled();
  });

  it("does not render the legacy recommended queries/dashboards section", async () => {
    renderScreen();
    await screen.findByText("Executive Project Summary");
    expect(screen.queryByRole("heading", { name: "Recommended Queries" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Recommended Dashboards" })).toBeNull();
  });

  it("shows a clean empty state for risks and opportunities", async () => {
    renderScreen();
    expect(
      await screen.findByText(
        "No risks detected from this project's data yet.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "No opportunities detected from this project's data yet.",
      ),
    ).toBeTruthy();
  });

  it("renders AI-derived risk/opportunity cards with severity badges", async () => {
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
              callout: {
                type: "risk",
                text: "Escalate with the supplier.",
              },
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
    expect(
      (await screen.findAllByText("Delivery lead time exceeds SLA threshold")).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Recommendation").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Escalate with the supplier.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SUP_Quality_CSV").length).toBeGreaterThan(0);
  });

  it("opens the AI answer modal when an AI-derived card is investigated", async () => {
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
              title: "Spend tracking over budget",
              summary: "Spend is up.",
              question: "How has total spend changed across recent periods?",
              chart: null,
              callout: null,
              sources: { tables: ["FIN_Spend_CSV"], documents: [] },
              executedAt: "2026-06-25T00:00:00Z",
            },
          ],
        },
      ],
    });
    renderScreen();
    expect((await screen.findAllByText("Spend tracking over budget")).length).toBeGreaterThan(0);
    const heading = screen.getByRole("heading", { name: "Spend tracking over budget" });
    const card = heading.closest("article") as HTMLElement;
    const moreActions = within(card).getByRole("button", { name: /More Actions/i });
    fireEvent.click(moreActions);
    const investigate = within(card).getByRole("button", { name: /investigate/i });
    fireEvent.click(investigate);
    const dialog = await screen.findByRole("dialog", { name: "AI Answer" });
    expect(dialog.textContent).toContain(
      "How has total spend changed across recent periods?",
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("shows a last-updated timestamp and Analyzing on refresh", async () => {
    renderScreen();
    expect(await screen.findByText(/Last updated:/)).toBeTruthy();
    let release: (() => void) | undefined;
    getInsight.mockReturnValue(
      new Promise((resolve) => {
        release = () => resolve(INSIGHT);
      }),
    );
    const refresh = screen.getByRole("button", { name: /refresh/i });
    fireEvent.click(refresh);
    expect(await screen.findByText("Analyzing…")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /refresh/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    release?.();
  });

  it("renders scoped inline insights and sends this project's id", async () => {
    suggestInsights.mockResolvedValue({
      projects: [
        {
          projectId: "42",
          projectName: "Boeing",
          projectColor: "#123456",
          insights: [
            {
              id: "ins-1",
              projectId: "42",
              projectName: "Boeing",
              projectColor: "#123456",
              insightType: "opportunity_supplier",
              severity: "recommendation",
              title: "Consolidate spend with top suppliers",
              summary: "Two suppliers account for most spend.",
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
    const heading = await screen.findByRole("heading", {
      name: "Insights & Opportunities",
    });
    expect(heading).toBeTruthy();
    await waitFor(() =>
      expect(suggestInsights).toHaveBeenCalledWith(3, 42),
    );
    const panel = heading.closest("section") as HTMLElement;
    expect(
      (await within(panel).findAllByText("Consolidate spend with top suppliers")).length,
    ).toBeGreaterThan(0);
  });

  it("has no residual card shadows in the page body", async () => {
    const { container } = renderScreen();
    await screen.findByText("Executive Project Summary");
    expect(container.querySelector('[class*="shadow"]')).toBeNull();
  });
});
