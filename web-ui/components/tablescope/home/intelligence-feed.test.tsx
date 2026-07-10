import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  handlers: [] as Array<(event: never) => void>,
  getPreferences: vi.fn(),
  getSnapshot: vi.fn(),
  updatePreferences: vi.fn(),
  stream: vi.fn(),
}));

vi.mock("@/lib/api/home-intelligence", () => ({
  getPreferences: mocks.getPreferences,
  getIntelligenceSnapshot: mocks.getSnapshot,
  updatePreferences: mocks.updatePreferences,
  streamHomeIntelligence: mocks.stream,
}));

vi.mock("@/lib/stores/report-builder-store", () => ({
  useReportBuilder: () => ({
    openPanel: vi.fn(),
    addInsightCard: vi.fn(),
    sections: [],
  }),
}));

vi.mock("@/lib/format-datetime", () => ({
  formatLastUpdated: () => "just now",
}));

vi.mock("./intelligence-card", () => ({
  IntelligenceCard: ({ card }: { card: { title: string } }) => (
    <div>{card.title}</div>
  ),
  LoadingCard: ({ projectName }: { projectName: string }) => (
    <div>Analyzing {projectName}</div>
  ),
}));

vi.mock("./intelligence-sidebar", () => ({
  IntelligenceSidebar: () => <aside />,
}));

vi.mock("./intelligence-strip", () => ({
  IntelligenceStrip: () => <header />,
}));

vi.mock("./report-builder-panel", () => ({
  ReportBuilderPanel: () => null,
}));

import { IntelligenceFeed } from "./intelligence-feed";

const preferences = {
  intelligence: {
    run_on_load: true,
    cross_project: true,
    email_digest: false,
    granularity: 3,
  },
};

function insight(id: string, projectId: string, title: string) {
  return {
    id,
    projectId,
    projectName: `Project ${projectId}`,
    projectColor: "#000000",
    insightType: `risk_${id}`,
    severity: "warning",
    title,
    summary: title,
    chart: null,
    callout: null,
    sources: { tables: [], documents: [] },
    executedAt: "2026-06-25T00:00:00Z",
  };
}

describe("IntelligenceFeed transient project failures", () => {
  beforeEach(() => {
    mocks.handlers.length = 0;
    mocks.getPreferences.mockReset().mockResolvedValue(preferences);
    mocks.getSnapshot.mockReset().mockResolvedValue({ snapshot: null });
    mocks.updatePreferences.mockReset().mockResolvedValue(preferences);
    mocks.stream.mockReset().mockImplementation((handler: (event: never) => void) => {
      mocks.handlers.push(handler);
      return new AbortController();
    });
  });

  it("clears an errored project's Analyzing card without showing Retry", async () => {
    render(<IntelligenceFeed />);
    await waitFor(() => expect(mocks.handlers).toHaveLength(1));

    act(() => {
      mocks.handlers[0]({
        type: "start",
        projects: [{ id: "1", name: "Busy Project", color: "#000000" }],
      } as never);
    });
    expect(screen.getByText("Analyzing Busy Project")).toBeTruthy();

    act(() => {
      mocks.handlers[0]({
        type: "project_error",
        projectId: "1",
        projectName: "Busy Project",
        error: "AI server is busy",
      } as never);
    });

    expect(screen.queryByText("Analyzing Busy Project")).toBeNull();
    expect(screen.queryByText("Retry")).toBeNull();
    expect(screen.queryByText(/AI intelligence hit an error/i)).toBeNull();
  });

  it("keeps the last good cards when a background refresh produces fewer results", async () => {
    mocks.getSnapshot.mockResolvedValue({
      snapshot: {
        granularity: 3,
        updatedAt: "2026-06-25T00:00:00Z",
        projects: [
          { id: "1", name: "Project 1", color: "#000000" },
          { id: "2", name: "Project 2", color: "#111111" },
        ],
        results: [
          {
            projectId: "1",
            projectName: "Project 1",
            projectColor: "#000000",
            insights: [insight("old-1", "1", "Saved insight one")],
          },
          {
            projectId: "2",
            projectName: "Project 2",
            projectColor: "#111111",
            insights: [insight("old-2", "2", "Saved insight two")],
          },
        ],
        synthesis: null,
      },
    });

    render(<IntelligenceFeed />);
    await waitFor(() => expect(mocks.handlers).toHaveLength(1));
    expect(screen.getByText("Saved insight one")).toBeTruthy();
    expect(screen.getByText("Saved insight two")).toBeTruthy();

    act(() => {
      mocks.handlers[0]({
        type: "start",
        projects: [
          { id: "1", name: "Project 1", color: "#000000" },
          { id: "2", name: "Project 2", color: "#111111" },
        ],
      } as never);
      mocks.handlers[0]({
        type: "project_complete",
        projectId: "1",
        projectName: "Project 1",
        projectColor: "#000000",
        insights: [insight("new-1", "1", "Partial refresh insight")],
      } as never);
      mocks.handlers[0]({
        type: "project_error",
        projectId: "2",
        projectName: "Project 2",
        error: "AI server is busy",
      } as never);
      mocks.handlers[0]({ type: "done", projectCount: 2 } as never);
    });

    expect(screen.getByText("Saved insight one")).toBeTruthy();
    expect(screen.getByText("Saved insight two")).toBeTruthy();
    expect(screen.queryByText("Partial refresh insight")).toBeNull();
    expect(screen.queryByText("Retry")).toBeNull();
  });
});
