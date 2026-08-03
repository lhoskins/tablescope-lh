import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { GraphNode } from "@/lib/ui/use-project-data";
import {
  KnowledgeGraphCanvas,
  centerLabel,
  connectorStroke,
  edgePath,
  insetPoint,
  moveToward,
  rectSidePoint,
} from "./knowledge-graph-canvas";

function node(over: Partial<GraphNode> & { id: number | string }): GraphNode {
  return {
    type: "document",
    label: `Node ${over.id}`,
    source_type: null,
    source_id: null,
    properties: {},
    graphKey: `document:${over.id}`,
    displayGroup: "Supporting & Governing Documents",
    confidence: 0.8,
    ...over,
  };
}

describe("knowledge graph canvas geometry helpers", () => {
  it("insetPoint moves the point toward the target by the given amount", () => {
    const p = insetPoint({ x: 0, y: 0 }, { x: 10, y: 0 }, 4);
    expect(p.x).toBeCloseTo(4);
    expect(p.y).toBeCloseTo(0);
  });

  it("edgePath emits a cubic Bezier curve (not a straight line)", () => {
    const d = edgePath({ x: 0, y: 0 }, { x: 100, y: 40 });
    expect(d.startsWith("M 0 0")).toBe(true);
    expect(d).toContain(" C ");
  });

  it("moveToward nudges the endpoint toward the target shape", () => {
    const p = moveToward({ x: 0, y: 0 }, { x: 0, y: 10 }, 2);
    expect(p.x).toBeCloseTo(0);
    expect(p.y).toBeCloseTo(2);
  });

  it("rectSidePoint attaches to the pill's vertical edge nearest the circle", () => {
    const rect = { x: 100, y: 200, w: 210, h: 38 };
    const midY = 200 + 38 / 2;
    // Circle to the LEFT of the pill → attach on the pill's LEFT edge.
    const left = rectSidePoint(rect, { x: 0, y: midY });
    expect(left.x).toBe(100);
    expect(left.y).toBeCloseTo(midY);
    // Circle to the RIGHT of the pill → attach on the pill's RIGHT edge.
    const right = rectSidePoint(rect, { x: 999, y: midY });
    expect(right.x).toBe(310);
    expect(right.y).toBeCloseTo(midY);
  });

  it("rectSidePoint stays on the side edge even when vertically offset", () => {
    const rect = { x: 100, y: 0, w: 210, h: 38 };
    // Circle far below and to the left: still the LEFT edge at mid-height,
    // never the top/bottom edge.
    const p = rectSidePoint(rect, { x: 0, y: 800 });
    expect(p.x).toBe(100);
    expect(p.y).toBeCloseTo(19);
  });

  it("centerLabel keeps short labels and drops file extensions", () => {
    expect(centerLabel("Supplier Qualification")).toBe("Supplier Qualification");
    expect(centerLabel("Quality_Manual.docx")).toBe("Quality_Manual");
  });

  it("centerLabel middle-ellipsizes long labels (head + tail)", () => {
    const out = centerLabel("SUP_Supplier_Quality_Manual_2026_Edition_Final");
    expect(out).toContain("\u2026");
    expect(out.startsWith("SUP_Supplier_Qua")).toBe(true);
    expect(out.endsWith("_Edition_Final")).toBe(true);
  });
});

describe("connectorStroke", () => {
  // Regression: when no trace-to-evidence is active (the default, normal
  // browsing state), edges must still render per their own
  // connectorStyle/relationshipStrength \u2014 not the flat solid "traced" style.
  it("honors dashed styling (Recommended) when no trace is active", () => {
    const s = connectorStroke("dashed", "recommended", false);
    expect(s.dash).toBe("8 6");
    expect(s.stroke).toBe("#fbbf24");
  });

  it("honors dotted styling (Inferred) when no trace is active", () => {
    const s = connectorStroke("dotted", "inferred", false);
    expect(s.dash).toBe("4 4");
  });

  it("renders solid, no dash, for Explicit evidence when no trace is active", () => {
    const s = connectorStroke("solid", "explicit", false);
    expect(s.dash).toBeUndefined();
  });

  it("still overrides to flat solid gray for an edge that IS part of an active trace", () => {
    const s = connectorStroke("dashed", "recommended", true);
    expect(s.dash).toBeUndefined();
    expect(s.stroke).toBe("#94a3b8");
  });
});

describe("KnowledgeGraphCanvas", () => {
  const center = node({
    id: 1,
    type: "project",
    label: "Boeing Project",
    graphKey: "project:1",
    displayGroup: "Project",
  });

  it("renders the center node with the navy gradient styling", () => {
    render(
      <KnowledgeGraphCanvas
        centerNode={center}
        nodes={[center, node({ id: 2 })]}
        edges={[{ id: 10, source: 1, target: 2, confidence: 0.95, type: "governs" }]}
        selectedNodeKey={null}
        tracedNodeIds={null}
        onNodeClick={() => {}}
      />,
    );
    const el = screen.getByTestId("kg-center-node");
    expect(el.getAttribute("style")).toContain("radial-gradient");
    expect(el.getAttribute("style")).toContain("#FFFFFF");
  });

  it("fires onNodeClick when a pill is clicked", () => {
    const onNodeClick = vi.fn();
    render(
      <KnowledgeGraphCanvas
        centerNode={center}
        nodes={[center, node({ id: 2, label: "Quality Manual" })]}
        edges={[{ id: 10, source: 1, target: 2, confidence: 0.95, type: "governs" }]}
        selectedNodeKey={null}
        tracedNodeIds={null}
        onNodeClick={onNodeClick}
      />,
    );
    fireEvent.click(screen.getByText("Quality Manual"));
    expect(onNodeClick).toHaveBeenCalledOnce();
  });

  it("does not render edge relationship labels on the lines by default", () => {
    const { container } = render(
      <KnowledgeGraphCanvas
        centerNode={center}
        nodes={[
          center,
          node({ id: 2, label: "Doc A" }),
          node({ id: 3, label: "Doc B" }),
        ]}
        edges={[
          { id: 10, source: 1, target: 2, confidence: 0.95, type: "governs" },
          { id: 11, source: 2, target: 3, confidence: 0.6, type: "related_to" },
        ]}
        selectedNodeKey={null}
        tracedNodeIds={null}
        onNodeClick={() => {}}
      />,
    );
    // No midpoint relationship labels are drawn, but the nodes + arrows are.
    expect(screen.queryByText("governs")).toBeNull();
    expect(screen.queryByText("related to")).toBeNull();
    expect(screen.getByText("Doc A")).toBeTruthy();
    expect(container.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("shortens a long center label and exposes the full label as a tooltip", () => {
    const longCenter = node({
      id: 1,
      type: "document",
      label: "SUP_Supplier_Quality_Manual_2026_Edition.docx",
      graphKey: "document:1",
    });
    render(
      <KnowledgeGraphCanvas
        centerNode={longCenter}
        nodes={[longCenter, node({ id: 2, label: "Doc A" })]}
        edges={[{ id: 10, source: 1, target: 2, confidence: 0.9, type: "governs" }]}
        selectedNodeKey={null}
        tracedNodeIds={null}
        onNodeClick={() => {}}
      />,
    );
    const el = screen.getByTestId("kg-center-node");
    expect(el.getAttribute("title")).toBe("SUP_Supplier_Quality_Manual_2026_Edition.docx");
    expect(el.textContent).toContain("\u2026");
  });

  it("renders a Recommended edge dashed and an Inferred edge dotted with no trace active", () => {
    const { container } = render(
      <KnowledgeGraphCanvas
        centerNode={center}
        nodes={[
          center,
          node({ id: 2, label: "Recommended Doc" }),
          node({ id: 3, label: "Inferred Doc" }),
        ]}
        edges={[
          {
            id: 10, source: 1, target: 2, confidence: 0.4, type: "reference",
            connectorStyle: "dashed", relationshipStrength: "recommended",
          },
          {
            id: 11, source: 1, target: 3, confidence: 0.75, type: "cites",
            connectorStyle: "dotted", relationshipStrength: "inferred",
          },
        ]}
        selectedNodeKey={null}
        tracedNodeIds={null}
        onNodeClick={() => {}}
      />,
    );
    const paths = Array.from(container.querySelectorAll("svg > path"));
    const dashArrays = paths.map((p) => p.getAttribute("stroke-dasharray"));
    expect(dashArrays).toContain("8 6"); // recommended \u2192 dashed
    expect(dashArrays).toContain("4 4"); // inferred \u2192 dotted
  });
});
