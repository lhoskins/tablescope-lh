import { describe, expect, it } from "vitest";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { HomeDocumentRow } from "@/lib/ui/use-shell-data";
import {
  buildHomeDevelopments,
  normalizeHomePersona,
  rankHomeInsights,
} from "./home-persona";

function insight(overrides: Partial<InsightCard>): InsightCard {
  return {
    id: "base",
    projectId: "7",
    projectName: "Operations",
    projectColor: "#2563eb",
    insightType: "trend",
    severity: "trend",
    title: "Operational trend",
    summary: "General operational performance changed.",
    chart: null,
    callout: null,
    sources: { tables: [], documents: [] },
    executedAt: "2026-08-22T00:00:00Z",
    ...overrides,
  };
}

describe("home persona composition", () => {
  it("falls back to the Executive persona for unsupported values", () => {
    expect(normalizeHomePersona("super_admin")).toBe("executive");
  });

  it("prioritizes persona-relevant insights without changing the available cards", () => {
    const service = insight({
      id: "service",
      title: "Service SLA breach risk",
      summary: "Incident resolution and SLA performance require attention.",
      severity: "warning",
    });
    const finance = insight({
      id: "finance",
      title: "Revenue and margin outlook",
      summary: "Revenue forecast and margin are improving.",
      severity: "trend",
    });

    expect(rankHomeInsights([finance, service], "cio")[0].id).toBe("service");
    expect(rankHomeInsights([finance, service], "cfo")[0].id).toBe("finance");
    expect(rankHomeInsights([finance, service], "cfo")).toHaveLength(2);
  });

  it("includes an AI-indexed document among key developments", () => {
    const document: HomeDocumentRow = {
      id: 21,
      name: "Annual Performance Review",
      projectId: 7,
      projectName: "Operations",
      aiStatus: "profiled",
      sharedBy: "Analyst",
      ownerId: 1,
      ownerName: "Analyst",
      createdAt: "2026-08-20T00:00:00Z",
      updatedAt: "2026-08-21T00:00:00Z",
      aiSummary: "The annual review summarizes revenue, risk, and strategic performance.",
    };

    const developments = buildHomeDevelopments(
      [insight({ id: "revenue", title: "Revenue outlook" })],
      [document],
      "ceo",
    );

    expect(developments.some((item) => item.kind === "document")).toBe(true);
    expect(developments.find((item) => item.kind === "document")?.title).toBe(
      "Annual Performance Review",
    );
  });
});
