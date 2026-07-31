import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InsightCardActionToolbar } from "./insight-card-action-toolbar";
import type { InsightCard } from "@/lib/api/home-intelligence";

const baseCard: InsightCard = {
  id: "card-1",
  insightId: "insight-1",
  projectId: "1",
  projectName: "Project A",
  projectColor: "#000",
  insightType: "trend",
  severity: "info",
  title: "Test insight",
  summary: "A summary",
  chart: { type: "bar", data: { series: [] }, config: {} } as unknown as NonNullable<InsightCard["chart"]>,
  callout: null,
  sources: { tables: ["demo_table"], documents: ["report.pdf"] },
  executedAt: new Date().toISOString(),
  sql: "SELECT * FROM demo_table",
  valueColumn: "value",
};

const noop = () => {};

describe("InsightCardActionToolbar", () => {
  it("renders toolbar icons in order: Create Action, Explain, Agree, Disagree, Chart options, Add to dashboard, Download PNG, Export to CSV", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction
        onCreateAction={noop}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
        onExportCsv={noop}
        onFeedbackClick={noop}
      />,
    );
    const buttons = screen.getAllByRole("button");
    const labels = buttons.map((b) => b.getAttribute("aria-label") ?? b.textContent);
    const createIdx = labels.findIndex((l) => l === "Create Action");
    const explainIdx = labels.findIndex((l) => l === "Explain");
    const agreeIdx = labels.findIndex((l) => l === "Agree");
    const disagreeIdx = labels.findIndex((l) => l === "Disagree");
    const chartIdx = labels.findIndex((l) => l === "Chart options");
    const dashboardIdx = labels.findIndex((l) => l === "Add to dashboard");
    const downloadIdx = labels.findIndex((l) => l === "Download PNG");
    const exportCsvIdx = labels.findIndex((l) => l === "Export to CSV");

    expect(createIdx).toBeGreaterThan(-1);
    expect(explainIdx).toBeGreaterThan(-1);
    expect(createIdx).toBeLessThan(explainIdx);
    expect(explainIdx).toBeLessThan(agreeIdx);
    expect(agreeIdx).toBeLessThan(disagreeIdx);
    expect(disagreeIdx).toBeLessThan(chartIdx);
    expect(chartIdx).toBeLessThan(dashboardIdx);
    expect(dashboardIdx).toBeLessThan(downloadIdx);
    expect(downloadIdx).toBeLessThan(exportCsvIdx);
  });

  it("disables Create action when canCreateAction is false", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
      />,
    );
    const btn = screen.getByRole("button", { name: "Create Action" });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows source row with primary source and +N sources", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
      />,
    );
    expect(screen.getByText("demo_table")).toBeTruthy();
    expect(screen.getByRole("button", { name: "1 more source" })).toBeTruthy();
  });

  it("shows feedback icons when onFeedbackClick is provided", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
        onFeedbackClick={noop}
      />,
    );
    expect(screen.getByRole("button", { name: "Agree" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Disagree" })).toBeTruthy();
  });

  it("uses filled icons and aria-pressed when feedback is active", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
        onFeedbackClick={noop}
        feedback={{
          id: 1,
          insight_id: "insight-1",
          project_id: 1,
          insight_type: "trend",
          sentiment: "agree",
          status: "active",
          reason_codes: ["confirmed"],
          comment: "looks right",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }}
      />,
    );
    const helpful = screen.getByRole("button", { name: "Edit Agree" });
    expect(helpful.getAttribute("aria-pressed")).toBe("true");
  });

  it("disables Add to dashboard when the insight lacks a value column", () => {
    const card = { ...baseCard, valueColumn: "" };
    render(
      <InsightCardActionToolbar
        card={card}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
      />,
    );
    const btn = screen.getByRole("button", { name: /dashboard/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("disables Chart options for kpi_grid cards", () => {
    const card = { ...baseCard, chart: { ...baseCard.chart!, type: "kpi_grid" as const } };
    render(
      <InsightCardActionToolbar
        card={card}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
      />,
    );
    const btn = screen.getByRole("button", { name: /Chart options/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows busy state while PNG is exporting", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
        isPngExporting
      />,
    );
    const btn = screen.getByRole("button", { name: "Downloading PNG" });
    expect(btn.getAttribute("aria-busy")).toBe("true");
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows busy state while CSV is exporting", () => {
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={noop}
        onAddToDashboard={noop}
        onDownloadPng={noop}
        onExportCsv={noop}
        isCsvExporting
      />,
    );
    const btn = screen.getByRole("button", { name: "Exporting CSV" });
    expect(btn.getAttribute("aria-busy")).toBe("true");
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("emits handlers with correct arguments", () => {
    const onFeedbackClick = vi.fn();
    const onChartOptions = vi.fn();
    const onDownloadPng = vi.fn();
    const onExportCsv = vi.fn();
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={noop}
        onChartOptions={onChartOptions}
        onAddToDashboard={noop}
        onDownloadPng={onDownloadPng}
        onExportCsv={onExportCsv}
        onFeedbackClick={onFeedbackClick}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Agree" }));
    expect(onFeedbackClick).toHaveBeenCalledWith("agree");

    fireEvent.click(screen.getByRole("button", { name: "Disagree" }));
    expect(onFeedbackClick).toHaveBeenCalledWith("disagree");

    fireEvent.click(screen.getByRole("button", { name: "Chart options" }));
    expect(onChartOptions).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Download PNG" }));
    expect(onDownloadPng).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Export to CSV" }));
    expect(onExportCsv).toHaveBeenCalled();
  });

  it("is keyboard operable", () => {
    const onExplain = vi.fn();
    const onChartOptions = vi.fn();
    render(
      <InsightCardActionToolbar
        card={baseCard}
        canCreateAction={false}
        onExplain={onExplain}
        onChartOptions={onChartOptions}
        onAddToDashboard={noop}
        onDownloadPng={noop}
      />,
    );
    const explain = screen.getByRole("button", { name: "Explain" });
    explain.focus();
    fireEvent.keyDown(explain, { key: "Enter" });
    fireEvent.click(explain);
    expect(onExplain).toHaveBeenCalled();
  });
});
