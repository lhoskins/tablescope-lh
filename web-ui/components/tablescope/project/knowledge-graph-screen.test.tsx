import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const mutateAsync = vi.fn().mockResolvedValue({});
const refetch = vi.fn().mockResolvedValue({});

const graphData = {
  centerNode: {
    id: 1,
    type: "project",
    label: "Boeing Project",
    source_type: null,
    source_id: null,
    properties: {},
    graphKey: "project:1",
  },
  nodes: [
    {
      id: 1,
      type: "project",
      label: "Boeing Project",
      source_type: null,
      source_id: null,
      properties: {},
      graphKey: "project:1",
    },
  ],
  edges: [],
  insightCards: [],
  gaps: [],
  recommendedActions: [],
  tracePaths: [],
  stats: { nodeCount: 1, edgeCount: 0 },
  lastUpdated: "2026-05-13T05:00:00+00:00",
  isCached: true,
};

vi.mock("@/lib/ui/use-project-data", () => ({
  useKnowledgeGraph: () => ({
    data: graphData,
    isLoading: false,
    isError: false,
    refetch,
  }),
  useRefreshKnowledgeGraph: () => ({
    mutateAsync,
    isPending: false,
    isError: false,
  }),
}));

vi.mock("./knowledge-graph-controls", () => ({
  KnowledgeGraphControls: () => <div data-testid="controls" />,
}));
vi.mock("./knowledge-graph-canvas", () => ({
  KnowledgeGraphCanvas: () => <div data-testid="canvas" />,
}));
vi.mock("./knowledge-graph-insight-panel", () => ({
  KnowledgeGraphInsightPanel: () => <div data-testid="panel" />,
}));

import { KnowledgeGraphScreen } from "./knowledge-graph-screen";

describe("KnowledgeGraphScreen header", () => {
  beforeEach(() => {
    mutateAsync.mockClear();
    refetch.mockClear();
  });

  it("renders the friendly last-updated timestamp and Cached badge", () => {
    render(<KnowledgeGraphScreen projectId={1} />);
    expect(screen.getByText(/last updated/i)).toBeTruthy();
    expect(screen.getByText("Cached")).toBeTruthy();
  });

  it("rebuilds the snapshot when Refresh is clicked", async () => {
    render(<KnowledgeGraphScreen projectId={1} />);
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(mutateAsync).toHaveBeenCalledOnce();
  });
});
