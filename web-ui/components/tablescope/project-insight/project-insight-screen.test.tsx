import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { push, getInsight, acknowledge, reviewed, reopen } = vi.hoisted(() => ({
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
  trendDetection: [{ id: "t1", label: "Spend up", description: "MoM +12%" }],
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
    acknowledge: (projectId: string, insightId: string) =>
      acknowledge(projectId, insightId),
    reviewed: (projectId: string) => reviewed(projectId),
    reopen: (projectId: string, insightId: string) =>
      reopen(projectId, insightId),
  },
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

describe("ProjectInsightScreen", () => {
  beforeEach(() => {
    push.mockClear();
    acknowledge.mockClear();
    reopen.mockClear();
    reviewed.mockReset();
    reviewed.mockResolvedValue({ items: [] });
    getInsight.mockReset();
    getInsight.mockResolvedValue(INSIGHT);
  });

  it("renders the approved layout sections", async () => {
    renderScreen();
    expect(
      await screen.findByText("Executive Project Summary"),
    ).toBeTruthy();
    expect(screen.getByText("AI-Generated Questions to Ask")).toBeTruthy();
    expect(screen.getByText("Trend Detection")).toBeTruthy();
    expect(screen.getByText("Recommended Dashboards")).toBeTruthy();
    expect(screen.getByText("Recommended Queries")).toBeTruthy();
    expect(screen.getByText("Recommended KPIs")).toBeTruthy();
    expect(screen.getByText("What Changed Since Last Visit")).toBeTruthy();
    expect(screen.getByText("Insight Validation Workflow")).toBeTruthy();
  });

  it("shows executive summary bullet categories", async () => {
    renderScreen();
    expect(await screen.findByText("Critical")).toBeTruthy();
    expect(screen.getByText("Warnings")).toBeTruthy();
    // "Opportunities" is both an executive-summary column and a card section.
    expect(screen.getAllByText("Opportunities").length).toBeGreaterThan(0);
    expect(screen.getByText("Recommendations")).toBeTruthy();
    expect(screen.getByText("Supplier A SLA breach")).toBeTruthy();
  });

  it("shows unanswerable questions in a Needs additional data section", async () => {
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
    expect(await screen.findByText("Needs additional data")).toBeTruthy();
    expect(
      screen.getByText("What is employee headcount by department?"),
    ).toBeTruthy();
    expect(
      screen.getByText("Add a source with the relevant data to enable it."),
    ).toBeTruthy();
  });

  it("shows suggestion status on recommended assets", async () => {
    renderScreen();
    // "Suggested" appears for dashboards + queries; KPI shows "Suggested" too.
    expect((await screen.findAllByText("Suggested")).length).toBeGreaterThan(0);
  });

  it("does not show Approve or Reject in the validation workflow", async () => {
    renderScreen();
    await screen.findByText("Insight Validation Workflow");
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /reject/i })).toBeNull();
  });

  it("marks an insight reviewed; it moves to the Reviewed tab", async () => {
    // After review, the insight is no longer 'new' in the report and the
    // reviewed-list endpoint returns it.
    const reviewedInsight = {
      ...INSIGHT,
      insightValidationWorkflow: [
        {
          id: "i1",
          title: "Supplier A risk",
          priority: "high",
          status: "reviewed",
          acknowledgedBy: "Leonard",
        },
      ],
    };
    acknowledge.mockImplementation(() => {
      getInsight.mockResolvedValue(reviewedInsight);
      reviewed.mockResolvedValue({
        items: [
          {
            insightId: "i1",
            title: "Supplier A risk",
            summary: "",
            category: "risk",
            severity: "high",
            note: null,
            reviewedByUserId: 1,
            reviewedByName: "Leonard",
            reviewedAt: "2026-06-25T00:00:00Z",
          },
        ],
      });
      return Promise.resolve({
        insightId: "i1",
        status: "reviewed",
        acknowledgedByUserId: 1,
        acknowledgedByName: "Leonard",
        acknowledgedAt: "2026-06-25T00:00:00Z",
      });
    });
    renderScreen();
    const btn = await screen.findByRole("button", { name: /mark reviewed/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(acknowledge).toHaveBeenCalledWith("42", "i1"),
    );
    // The Open tab no longer shows the reviewed item.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /mark reviewed/i })).toBeNull(),
    );
    // It now appears under the Reviewed tab (with the reviewer name).
    fireEvent.click(screen.getByRole("button", { name: /^Reviewed/ }));
    expect(await screen.findByText("Supplier A risk")).toBeTruthy();
    expect(
      (await screen.findAllByText((t) => t.includes("by Leonard"))).length,
    ).toBeGreaterThan(0);
  });

  it("filters out empty items instead of showing placeholder fallbacks", async () => {
    getInsight.mockResolvedValue({
      ...INSIGHT,
      questionsToAsk: [{ id: "q1", question: "   ", reason: "" }],
      trendDetection: [{ id: "t1", label: "Trend A", description: "" }],
      recommendedDashboards: [{ id: "d1", title: "", status: "suggested" }],
      recommendedQueries: [
        {
          id: "rq1",
          title: "",
          businessQuestion: "What drove late deliveries?",
          status: "suggested",
        },
      ],
      recommendedKpis: [
        { id: "k1", name: "", status: "recommended", currentValue: null },
      ],
      insightValidationWorkflow: [{ id: "i1", title: "", status: "new" }],
    });
    renderScreen();
    // Trend A here has a label, so it still renders (the model must derive a
    // real label) — but empty-title items must not render placeholder text.
    await screen.findByText("Recommended Queries");
    expect(screen.queryByText("Query")).toBeNull();
    expect(screen.queryByText("KPI")).toBeNull();
    expect(screen.queryByText("Dashboard")).toBeNull();
    expect(screen.getByText("No query suggestions.")).toBeTruthy();
    expect(screen.getByText("No KPI suggestions.")).toBeTruthy();
    expect(screen.getByText("No dashboard suggestions.")).toBeTruthy();
    expect(screen.getByText("No suggested questions yet.")).toBeTruthy();
    expect(screen.getByText("No insights to review.")).toBeTruthy();
  });

  it("opens the AI answer modal (no navigation) when a question is clicked", async () => {
    renderScreen();
    const q = await screen.findByText("Why did Supplier A slip?");
    fireEvent.click(q);
    // Opens the inline modal rather than routing to the AI Assistant page.
    const dialog = await screen.findByRole("dialog", { name: "AI Answer" });
    expect(dialog.textContent).toContain("Why did Supplier A slip?");
    expect(push).not.toHaveBeenCalled();
  });

  it("opens the same AI answer modal from the custom question box", async () => {
    renderScreen();
    const input = await screen.findByLabelText(
      "Ask a question about this project",
    );
    fireEvent.change(input, {
      target: { value: "What is the total spend?" },
    });
    fireEvent.keyDown(input, { key: "Enter" });
    const dialog = await screen.findByRole("dialog", { name: "AI Answer" });
    expect(dialog.textContent).toContain("What is the total spend?");
    expect(push).not.toHaveBeenCalled();
  });

  it("opens the query preview modal when a recommended query's Generate is clicked", async () => {
    renderScreen();
    await screen.findByText("Recommended Queries");
    // The recommended query "Late shipments" has a Generate button.
    const generateButtons = screen.getAllByRole("button", { name: /generate/i });
    fireEvent.click(generateButtons[generateButtons.length - 1]);
    expect(
      await screen.findByRole("dialog", { name: "Generate Query" }),
    ).toBeTruthy();
  });

  it("opens the dashboard generation modal when a recommended dashboard's Generate is clicked", async () => {
    renderScreen();
    await screen.findByText("Recommended Dashboards");
    const generateButtons = screen.getAllByRole("button", { name: /generate/i });
    fireEvent.click(generateButtons[0]);
    expect(
      await screen.findByRole("dialog", { name: "Generate Dashboard" }),
    ).toBeTruthy();
  });

  it("shows a clean empty state for risks, trends, and opportunities", async () => {
    renderScreen();
    expect(
      await screen.findByText(
        "No risks detected from this project's data yet.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("No trends detected from this project's data yet."),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "No opportunities detected from this project's data yet.",
      ),
    ).toBeTruthy();
  });

  it("renders risk/opportunity cards with severity badges", async () => {
    getInsight.mockResolvedValue({
      ...INSIGHT,
      risks: [
        {
          id: "risk-1",
          insightType: "risk_sla",
          title: "Delivery lead time exceeds SLA threshold",
          summary: "Average lead time is high.",
          severity: "critical",
          recommendedAction: "Escalate with the supplier.",
          question: "Which suppliers exceed the SLA threshold?",
          supportingSources: ["SUP_Quality_CSV"],
        },
      ],
      opportunities: [
        {
          id: "opp-1",
          insightType: "opportunity_supplier",
          title: "Top-performing suppliers identified",
          summary: "Consolidate with the strongest suppliers.",
          severity: "recommendation",
          question: "Which suppliers have the highest performance scores?",
          supportingSources: [],
        },
      ],
    });
    renderScreen();
    expect(
      await screen.findByText("Delivery lead time exceeds SLA threshold"),
    ).toBeTruthy();
    // Deterministic severity badge labels (Business Insight style).
    expect(screen.getByText("Recommendation")).toBeTruthy();
    expect(screen.getByText("Escalate with the supplier.")).toBeTruthy();
    expect(screen.getByText("SUP_Quality_CSV")).toBeTruthy();
  });

  it("opens the AI answer modal (no navigation) when a card is investigated", async () => {
    getInsight.mockResolvedValue({
      ...INSIGHT,
      trends: [
        {
          id: "trend-1",
          insightType: "trend_spend",
          title: "Spend tracking over budget",
          summary: "Spend is up.",
          severity: "warning",
          question: "How has total spend changed across recent periods?",
          supportingSources: ["FIN_Spend_CSV"],
        },
      ],
    });
    renderScreen();
    await screen.findByText("Spend tracking over budget");
    const investigate = screen.getAllByRole("button", {
      name: /investigate/i,
    });
    fireEvent.click(investigate[0]);
    const dialog = await screen.findByRole("dialog", { name: "AI Answer" });
    expect(dialog.textContent).toContain(
      "How has total spend changed across recent periods?",
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("shows reviewed insights in the Reviewed tab and can reopen one", async () => {
    reviewed.mockResolvedValue({
      items: [
        {
          insightId: "i9",
          title: "Reviewed supplier risk",
          summary: "Confirmed and mitigated",
          category: "risk",
          severity: "high",
          note: null,
          reviewedByUserId: 1,
          reviewedByName: "Leonard",
          reviewedAt: "2026-06-25T00:00:00Z",
        },
      ],
    });
    renderScreen();
    // Switch to the Reviewed tab.
    fireEvent.click(await screen.findByRole("button", { name: /^Reviewed/ }));
    expect(await screen.findByText("Reviewed supplier risk")).toBeTruthy();
    const reopenBtn = await screen.findByRole("button", { name: /reopen/i });
    fireEvent.click(reopenBtn);
    await waitFor(() =>
      expect(reopen).toHaveBeenCalledWith("42", "i9"),
    );
  });
});
