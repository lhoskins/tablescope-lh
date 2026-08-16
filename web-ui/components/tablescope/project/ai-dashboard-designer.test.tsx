import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const post = vi.fn();
const push = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div>chart preview</div>,
}));

import { AIDashboardDesigner } from "./ai-dashboard-designer";

function review(status: "fully_supported" | "partially_supported" | "not_supported") {
  return {
    supportStatus: status,
    supportSummary: "Validated against project data.",
    missingRequirements: status === "fully_supported" ? [] : ["SLA performance"],
    questions: [],
    chartRecommendations: [
      { chartType: "line", label: "Trend line", compatible: true, reason: "Date plus measure" },
    ],
    sources: [{ viewName: "incidents", fileName: "incidents.csv", columns: [{ name: "opened_at", type: "date" }] }],
    suggestion: status === "not_supported" ? null : {
      id: "one",
      title: "Incident Operations Insights",
      description: "Operational view",
      businessPurpose: "Monitor risk",
      audience: "operational",
      widgets: [{ title: "Demand trend", chartType: "line", businessQuestion: "Opened over time", status: "valid", sql: "SELECT 1", chart: null, previewData: { columns: ["period", "count"], rows: [{ period: "Jul", count: 10 }] } }],
      kpis: ["Open backlog"],
      dataSources: ["incidents"],
      confidence: 0.9,
      qualityScore: 90,
      knowledgeGraphContext: { risks: ["Backlog is rising"] },
    },
  };
}

function renderDesigner({
  mode = "create",
  dashboardId,
}: {
  mode?: "create" | "add_insight";
  dashboardId?: number;
} = {}) {
  const client = new QueryClient();
  const onApplied = vi.fn();
  const notify = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AIDashboardDesigner
        open
        projectId="44"
        mode={mode}
        dashboardId={dashboardId}
        onClose={vi.fn()}
        onApplied={onApplied}
        notify={notify}
      />
    </QueryClientProvider>,
  );
  return { onApplied, notify };
}

describe("AIDashboardDesigner", () => {
  beforeEach(() => {
    post.mockReset();
    push.mockReset();
  });

  it("reviews, previews and applies a fully-supported dashboard", async () => {
    post
      .mockResolvedValueOnce(review("fully_supported"))
      .mockResolvedValueOnce({ dashboard_id: 91, dashboard_name: "Incident Operations Insights", status: "created" });
    const { onApplied } = renderDesigner();

    fireEvent.change(screen.getByLabelText(/what do you want people/i), { target: { value: "Show incident demand and SLA risk" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Fully supported");

    fireEvent.click(screen.getByRole("button", { name: /preview servicenow-style dashboard/i }));
    expect(screen.getByText("Incident Operations Insights")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^create dashboard$/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(91));
    expect(post).toHaveBeenLastCalledWith(
      "/api/ai/actions/dashboard-designer/apply",
      expect.objectContaining({ mode: "create", support_status: "fully_supported" }),
    );
  });

  it("does not allow a partial design to preview until the supported subset is approved", async () => {
    post.mockResolvedValueOnce(review("partially_supported"));
    renderDesigner();
    fireEvent.change(screen.getByLabelText(/what do you want people/i), { target: { value: "Show incident SLA risk" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Partially supported");

    const preview = screen.getByRole("button", { name: /preview servicenow-style dashboard/i });
    expect(preview).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(preview).not.toBeDisabled();
  });

  it("starts datasource onboarding when the request is unsupported", async () => {
    post.mockResolvedValueOnce(review("not_supported"));
    renderDesigner();
    fireEvent.change(screen.getByLabelText(/what do you want people/i), { target: { value: "Show unsupported information" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Not supported");
    fireEvent.click(screen.getByRole("button", { name: /upload or connect data/i }));
    expect(push).toHaveBeenCalledWith("/projects/44/data-sources?return=dashboards");
  });

  it("adds one validated insight without regenerating the dashboard", async () => {
    post
      .mockResolvedValueOnce(review("fully_supported"))
      .mockResolvedValueOnce({ dashboard_id: 91, dashboard_name: "Incident Operations Insights", status: "updated" });
    const { onApplied } = renderDesigner({ mode: "add_insight", dashboardId: 91 });

    fireEvent.change(screen.getByLabelText(/what additional decision/i), { target: { value: "Show incidents by site" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Fully supported");
    fireEvent.click(screen.getByRole("button", { name: /preview servicenow-style dashboard/i }));
    fireEvent.click(screen.getByRole("button", { name: /^add insight$/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(91));
    expect(post).toHaveBeenLastCalledWith(
      "/api/ai/actions/dashboard-designer/apply",
      expect.objectContaining({ mode: "add_insight", dashboard_id: 91 }),
    );
  });
});
