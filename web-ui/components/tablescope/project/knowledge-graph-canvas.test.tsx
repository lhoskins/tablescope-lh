import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { GraphNode } from "@/lib/ui/use-project-data";
import {
  KnowledgeGraphCanvas,
  edgePath,
  insetPoint,
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

  it("hides labels for low-confidence non-center edges to cut clutter", () => {
    render(
      <KnowledgeGraphCanvas
        centerNode={center}
        nodes={[
          center,
          node({ id: 2, label: "Doc A" }),
          node({ id: 3, label: "Doc B" }),
        ]}
        edges={[
          // center edge -> labelled
          { id: 10, source: 1, target: 2, confidence: 0.6, type: "governs" },
          // low-confidence source-to-source -> label hidden
          { id: 11, source: 2, target: 3, confidence: 0.6, type: "related_to" },
        ]}
        selectedNodeKey={null}
        tracedNodeIds={null}
        onNodeClick={() => {}}
      />,
    );
    expect(screen.getByText("governs")).toBeTruthy();
    expect(screen.queryByText("related to")).toBeNull();
  });
});
