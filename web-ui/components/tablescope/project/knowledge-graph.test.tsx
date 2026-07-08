import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { KnowledgeGraphInsightCard } from "@/lib/ui/use-project-data";
import { KnowledgeGraphInsightPanel } from "./knowledge-graph-insight-panel";
import { alertSignFor, paletteFor } from "./knowledge-graph-style";

function makeCard(
  overrides: Partial<KnowledgeGraphInsightCard>,
): KnowledgeGraphInsightCard {
  return {
    id: "c1",
    nodeKey: "insight:1",
    category: "risk",
    severity: "urgent",
    title: "Overdue CAPAs rising",
    summary: "Overdue corrective actions are trending up.",
    confidence: 0.88,
    evidencePath: ["process:capa", "kpi:closure"],
    sourceDocuments: ["Quality Manual"],
    sourceTables: [],
    sourceQueries: [],
    sourceDashboards: [],
    supportedKpis: ["On-time Closure"],
    traceToEvidence: { nodeIds: [1, 2], edgeIds: [10], nodeKeys: [] },
    ...overrides,
  };
}

describe("KnowledgeGraphInsightPanel", () => {
  it("groups cards by category under AI-Home-style headings", () => {
    render(
      <KnowledgeGraphInsightPanel
        title="Corrective Action Process"
        cards={[
          makeCard({ id: "r", category: "risk", title: "Risk card" }),
          makeCard({ id: "o", category: "opportunity", severity: "opportunity", title: "Opp card" }),
        ]}
        tracingCardId={null}
        onTrace={() => {}}
      />,
    );
    expect(screen.getByText("Knowledge Graph Risks")).toBeTruthy();
    expect(screen.getByText("Knowledge Graph Opportunities")).toBeTruthy();
    expect(screen.getByText("Risk card")).toBeTruthy();
    expect(screen.getByText("Opp card")).toBeTruthy();
  });

  it("renders a Trace to Evidence button and fires the callback", () => {
    const onTrace = vi.fn();
    render(
      <KnowledgeGraphInsightPanel
        title="Center"
        cards={[makeCard({})]}
        tracingCardId={null}
        onTrace={onTrace}
      />,
    );
    const btn = screen.getByRole("button", { name: /trace to evidence/i });
    fireEvent.click(btn);
    expect(onTrace).toHaveBeenCalledOnce();
  });

  it("hides the Trace button when there is no evidence path", () => {
    render(
      <KnowledgeGraphInsightPanel
        title="Center"
        cards={[makeCard({ traceToEvidence: { nodeIds: [], edgeIds: [], nodeKeys: [] } })]}
        tracingCardId={null}
        onTrace={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /trace to evidence/i })).toBeNull();
  });

  it("shows an empty state when there are no cards", () => {
    render(
      <KnowledgeGraphInsightPanel
        title="Center"
        cards={[]}
        tracingCardId={null}
        onTrace={() => {}}
      />,
    );
    expect(screen.getByText(/no business insights available for this node yet/i)).toBeTruthy();
  });
});

describe("knowledge graph style helpers", () => {
  it("uses the navy center palette when isCenter is true", () => {
    expect(paletteFor("process", true).border).toBe("#0F172A");
    expect(paletteFor("process", false).border).not.toBe("#0F172A");
  });

  it("maps finding node types to alert signs", () => {
    expect(alertSignFor("risk")).toBe("risk");
    expect(alertSignFor("warning")).toBe("warning");
    expect(alertSignFor("opportunity")).toBe("opportunity");
    expect(alertSignFor("gap")).toBe("gap");
    expect(alertSignFor("recommendation")).toBe("action");
    expect(alertSignFor("document")).toBeNull();
  });
});
