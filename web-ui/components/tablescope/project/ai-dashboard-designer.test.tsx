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

function review(
  status: "fully_supported" | "partially_supported" | "not_supported",
  options: { primaryDimensionCandidates?: unknown[]; widgets?: unknown[] } = {},
) {
  return {
    supportStatus: status,
    supportSummary: "Validated against project data.",
    missingRequirements: status === "fully_supported" ? [] : ["SLA performance"],
    questions: [],
    chartRecommendations: [
      { chartType: "line", label: "Trend line", compatible: true, reason: "Date plus measure" },
    ],
    sources: [{ viewName: "incidents", fileName: "incidents.csv", columns: [{ name: "opened_at", type: "date" }] }],
    primaryDimensionCandidates: options.primaryDimensionCandidates ?? [],
    suggestion: status === "not_supported" ? null : {
      id: "one",
      title: "Incident Operations Insights",
      description: "Operational view",
      businessPurpose: "Monitor risk",
      audience: "operational",
      widgets: options.widgets ?? [{ title: "Demand trend", chartType: "line", businessQuestion: "Opened over time", status: "valid", sql: "SELECT 1", chart: null, previewData: { columns: ["period", "count"], rows: [{ period: "Jul", count: 10 }] } }],
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
  mode?: "create" | "add_insight" | "edit_dashboard";
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

  it("builds an enumerated prompt from specific chart rows and enables submit without free text", async () => {
    post.mockResolvedValueOnce(review("fully_supported"));
    renderDesigner();

    const submit = screen.getByRole("button", { name: /analyze data/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText(/vendor spend trend/i), {
      target: { value: "Vendor spend trend over time" },
    });
    fireEvent.click(screen.getByRole("button", { name: /\+ add another chart/i }));
    fireEvent.change(screen.getByPlaceholderText(/high-priority incidents by priority/i), {
      target: { value: "High-priority incidents by priority" },
    });

    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);
    await screen.findByText("Fully supported");

    const [, body] = post.mock.calls[0];
    expect(body.prompt).toContain("Create exactly one widget for each of the following 2 requested chart(s)");
    expect(body.prompt).toContain("1. Vendor spend trend over time");
    expect(body.prompt).toContain("2. High-priority incidents by priority");
  });

  it("flags a mismatch between requested and generated chart counts in the review step", async () => {
    // review() stubs a suggestion with exactly one widget.
    post.mockResolvedValueOnce(review("fully_supported"));
    renderDesigner();

    fireEvent.change(screen.getByPlaceholderText(/vendor spend trend/i), {
      target: { value: "Vendor spend trend over time" },
    });
    fireEvent.click(screen.getByRole("button", { name: /\+ add another chart/i }));
    fireEvent.change(screen.getByPlaceholderText(/high-priority incidents by priority/i), {
      target: { value: "High-priority incidents by priority" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));

    await screen.findByText(/Requested 2 charts; AI proposed 1\./);
  });

  it("shows Specific charts, chart type/unit and Additional context on the Edit dashboard screen too", async () => {
    post
      .mockResolvedValueOnce(review("fully_supported"))
      .mockResolvedValueOnce({ dashboard_id: 91, dashboard_name: "Incident Operations Insights", status: "updated" });
    const { onApplied } = renderDesigner({ mode: "edit_dashboard", dashboardId: 91 });

    // The "Specific charts (optional)" section -- previously create-only --
    // must be present and usable on the edit screen.
    expect(screen.getByText("Specific charts (optional)")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/vendor spend trend/i), {
      target: { value: "Vendor spend trend over time" },
    });
    // Naming a chart relabels the free-text field to "Additional context".
    expect(screen.getByText("Additional context (optional)")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Fully supported");
    fireEvent.click(screen.getByRole("button", { name: /preview servicenow-style dashboard/i }));
    fireEvent.click(screen.getByRole("button", { name: /apply dashboard changes/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(91));
    const [reviewCall] = post.mock.calls;
    const [, reviewBody] = reviewCall;
    expect(reviewBody.chart_overrides).toEqual([
      expect.objectContaining({ label: "Vendor spend trend over time" }),
    ]);
    expect(post).toHaveBeenLastCalledWith(
      "/api/ai/actions/dashboard-designer/apply",
      expect.objectContaining({ mode: "edit_dashboard", dashboard_id: 91, currency: "USD" }),
    );
  });

  it("defaults currency to USD and sends the selected currency through review and apply", async () => {
    post
      .mockResolvedValueOnce(review("fully_supported"))
      .mockResolvedValueOnce({ dashboard_id: 91, dashboard_name: "Incident Operations Insights", status: "created" });
    const { onApplied } = renderDesigner();

    expect(screen.getByLabelText(/currency/i)).toHaveValue("USD");
    fireEvent.change(screen.getByLabelText(/currency/i), { target: { value: "EUR" } });

    fireEvent.change(screen.getByLabelText(/what do you want people/i), { target: { value: "Show revenue and backlog" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Fully supported");
    const [, reviewBody] = post.mock.calls[0];
    expect(reviewBody.currency).toBe("EUR");

    fireEvent.click(screen.getByRole("button", { name: /preview servicenow-style dashboard/i }));
    fireEvent.click(screen.getByRole("button", { name: /^create dashboard$/i }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(91));
    expect(post).toHaveBeenLastCalledWith(
      "/api/ai/actions/dashboard-designer/apply",
      expect.objectContaining({ currency: "EUR" }),
    );
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

  it("has no Site/Region primary-dimension dropdown on the Describe step", () => {
    renderDesigner();
    expect(screen.queryByLabelText(/primary dimension/i)).toBeNull();
    expect(screen.queryByText(/not listed.*generate from ai/i)).toBeNull();
  });

  it("shows a full-coverage AI-discovered dimension and sends it on apply", async () => {
    const twoWidgets = [
      { title: "Revenue by Unit", chartType: "bar", businessQuestion: "Revenue by business unit", status: "valid", sql: "SELECT 1", chart: null, previewData: { columns: ["business_unit", "revenue"], rows: [{ business_unit: "East", revenue: 100 }] } },
      { title: "Backlog by Unit", chartType: "bar", businessQuestion: "Backlog by business unit", status: "valid", sql: "SELECT 1", chart: null, previewData: { columns: ["business_unit", "backlog"], rows: [{ business_unit: "East", backlog: 20 }] } },
    ];
    post
      .mockResolvedValueOnce(review("fully_supported", {
        widgets: twoWidgets,
        primaryDimensionCandidates: [
          {
            field: "business_unit", label: "Business Unit", compatibleCount: 2, totalCount: 2,
            fullCoverage: true, compatibleWidgets: ["Revenue by Unit", "Backlog by Unit"], incompatibleWidgets: [],
          },
        ],
      }))
      .mockResolvedValueOnce({ dashboard_id: 91, dashboard_name: "Revenue Dashboard", status: "created" });
    const { onApplied } = renderDesigner();

    fireEvent.change(screen.getByLabelText(/what do you want people/i), { target: { value: "Show revenue by business unit" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Fully supported");

    expect(screen.getByText("Primary dimension compatibility")).toBeTruthy();
    expect(screen.getByText("Full coverage")).toBeTruthy();
    const labelInput = screen.getByDisplayValue("Business Unit");
    fireEvent.change(labelInput, { target: { value: "Unit" } });

    fireEvent.click(screen.getByRole("button", { name: /preview servicenow-style dashboard/i }));
    fireEvent.click(screen.getByRole("button", { name: /^create dashboard$/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(91));
    expect(post).toHaveBeenLastCalledWith(
      "/api/ai/actions/dashboard-designer/apply",
      expect.objectContaining({
        primary_dimensions: [{ field: "business_unit", label: "Unit" }],
      }),
    );
  });

  it("does not send a partial dimension until its incompatible chart is removed", async () => {
    const widgets = [
      { title: "Revenue by Unit", chartType: "bar", businessQuestion: "Revenue by business unit", status: "valid", sql: "SELECT 1", chart: null, previewData: { columns: ["business_unit", "revenue"], rows: [{ business_unit: "East", revenue: 100 }] } },
      { title: "Total Revenue", chartType: "kpi", businessQuestion: "Total revenue", status: "valid", sql: "SELECT 1", chart: null, previewData: { columns: ["revenue"], rows: [{ revenue: 4200 }] } },
    ];
    post
      .mockResolvedValueOnce(review("fully_supported", {
        widgets,
        primaryDimensionCandidates: [
          {
            field: "business_unit", label: "Business Unit", compatibleCount: 1, totalCount: 2,
            fullCoverage: false, compatibleWidgets: ["Revenue by Unit"],
            incompatibleWidgets: [{ title: "Total Revenue" }],
          },
        ],
      }))
      .mockResolvedValueOnce({ dashboard_id: 91, dashboard_name: "Revenue Dashboard", status: "created" });
    const { onApplied } = renderDesigner();

    fireEvent.change(screen.getByLabelText(/what do you want people/i), { target: { value: "Show revenue by business unit" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze data/i }));
    await screen.findByText("Fully supported");

    expect(screen.getByText("1/2 charts")).toBeTruthy();
    expect(screen.getByText("Total Revenue", { exact: false })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /remove incompatible chart/i }));
    await waitFor(() => expect(screen.getByText("Full coverage")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /preview servicenow-style dashboard/i }));
    fireEvent.click(screen.getByRole("button", { name: /^create dashboard$/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(91));
    const [, applyBody] = post.mock.calls[1];
    expect(applyBody.primary_dimensions).toEqual([{ field: "business_unit", label: "Business Unit" }]);
    expect(applyBody.suggestion.widgets.map((w: { title: string }) => w.title)).toEqual(["Revenue by Unit"]);
  });
});
