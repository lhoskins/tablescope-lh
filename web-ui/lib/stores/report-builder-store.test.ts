import { beforeEach, describe, expect, it } from "vitest";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { useReportBuilder } from "./report-builder-store";

function card(overrides: Partial<InsightCard> = {}): InsightCard {
  return {
    id: "1-risk_sla-1",
    projectId: "1",
    projectName: "Supply Chain",
    projectColor: "#185FA5",
    insightType: "risk_sla",
    severity: "urgent",
    title: "Delivery lead time exceeds SLA",
    summary: "Average lead time is **22 days**.",
    chart: null,
    callout: null,
    sources: { tables: ["shipments"], documents: [] },
    executedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("report-builder-store", () => {
  beforeEach(() => {
    useReportBuilder.getState().reset();
    useReportBuilder.getState().closePanel();
  });

  it("addInsightCard adds a section, opens the panel, and stores a preview", () => {
    useReportBuilder.getState().addInsightCard(card());
    const s = useReportBuilder.getState();
    expect(s.open).toBe(true);
    expect(s.sections).toHaveLength(1);
    expect(s.sections[0].kind).toBe("insight");
    expect(s.previews[s.sections[0].id].title).toContain("lead time");
  });

  it("de-dupes the same project + insight type", () => {
    const store = useReportBuilder.getState();
    store.addInsightCard(card());
    store.addInsightCard(card({ id: "1-risk_sla-2" }));
    expect(useReportBuilder.getState().sections).toHaveLength(1);
  });

  it("allows different insight types for the same project", () => {
    const store = useReportBuilder.getState();
    store.addInsightCard(card());
    store.addInsightCard(card({ id: "1-trend-1", insightType: "trend_spend" }));
    expect(useReportBuilder.getState().sections).toHaveLength(2);
  });

  it("addTextBlock and updateTextBlock", () => {
    useReportBuilder.getState().addTextBlock();
    const id = useReportBuilder.getState().sections[0].id;
    useReportBuilder.getState().updateTextBlock(id, "Quarterly note");
    expect(useReportBuilder.getState().sections[0].text).toBe("Quarterly note");
  });

  it("removeSection drops the section and its preview", () => {
    useReportBuilder.getState().addInsightCard(card());
    const id = useReportBuilder.getState().sections[0].id;
    useReportBuilder.getState().removeSection(id);
    const s = useReportBuilder.getState();
    expect(s.sections).toHaveLength(0);
    expect(s.previews[id]).toBeUndefined();
  });

  it("reorderSections moves a section", () => {
    const store = useReportBuilder.getState();
    store.addInsightCard(card());
    store.addInsightCard(card({ id: "x", insightType: "trend_spend" }));
    const firstId = useReportBuilder.getState().sections[0].id;
    store.reorderSections(0, 1);
    expect(useReportBuilder.getState().sections[1].id).toBe(firstId);
  });

  it("reset clears title, sections, and previews", () => {
    const store = useReportBuilder.getState();
    store.setTitle("My report");
    store.addInsightCard(card());
    store.reset();
    const s = useReportBuilder.getState();
    expect(s.title).toBe("Untitled report");
    expect(s.sections).toHaveLength(0);
    expect(Object.keys(s.previews)).toHaveLength(0);
  });
});
