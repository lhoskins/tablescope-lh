import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { push, getInsight, acknowledge } = vi.hoisted(() => ({
  push: vi.fn(),
  getInsight: vi.fn(),
  acknowledge: vi.fn().mockResolvedValue({
    insightId: "i1",
    status: "reviewed",
    acknowledgedByUserId: 1,
    acknowledgedByName: "Leonard",
    acknowledgedAt: "2026-06-25T00:00:00Z",
  }),
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

vi.mock("@/components/tablescope/project/ai-dashboard-suggestions-modal", () => ({
  AIDashboardSuggestionsModal: ({
    open,
    initialPrompt,
  }: {
    open: boolean;
    initialPrompt?: string;
  }) =>
    open ? (
      <div role="dialog" aria-label="Generate Dashboard">
        {initialPrompt}
      </div>
    ) : null,
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
    expect(screen.getByText("Opportunities")).toBeTruthy();
    expect(screen.getByText("Recommendations")).toBeTruthy();
    expect(screen.getByText("Supplier A SLA breach")).toBeTruthy();
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

  it("marks an insight reviewed and updates status", async () => {
    let reviewed = false;
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
    getInsight.mockImplementation(() =>
      Promise.resolve(reviewed ? reviewedInsight : INSIGHT),
    );
    acknowledge.mockImplementation(() => {
      reviewed = true;
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
    expect(await screen.findByText("Reviewed by Leonard")).toBeTruthy();
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
});
