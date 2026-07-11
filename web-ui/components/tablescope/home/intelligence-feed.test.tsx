import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import type { IntelligenceEvent } from "@/lib/api/home-intelligence";

const {
  push,
  streamHomeIntelligence,
  getPreferences,
  getIntelligenceSnapshot,
  updatePreferences,
} = vi.hoisted(() => ({
  push: vi.fn(),
  streamHomeIntelligence: vi.fn(),
  getPreferences: vi.fn(),
  getIntelligenceSnapshot: vi.fn(),
  updatePreferences: vi.fn(),
}));

// Grab the latest onEvent handler passed to the (mocked) SSE stream so the
// test can drive project_complete / done frames deterministically.
let lastOnEvent: ((e: IntelligenceEvent) => void) | null = null;

vi.mock("@/lib/api/home-intelligence", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/home-intelligence")>()),
  streamHomeIntelligence: (onEvent: (e: IntelligenceEvent) => void) => {
    lastOnEvent = onEvent;
    return streamHomeIntelligence(onEvent);
  },
  getPreferences: () => getPreferences(),
  getIntelligenceSnapshot: () => getIntelligenceSnapshot(),
  updatePreferences: (v: unknown) => updatePreferences(v),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

import { IntelligenceFeed } from "./intelligence-feed";

const PROJECTS = [
  { id: "1", name: "Alpha", color: "#111111" },
  { id: "2", name: "Beta", color: "#222222" },
];

const SNAPSHOT = {
  granularity: 3,
  updatedAt: "2026-06-25T00:00:00Z",
  projects: PROJECTS,
  results: [
    {
      projectId: "1",
      projectName: "Alpha",
      projectColor: "#111111",
      insights: [
        {
          id: "a1",
          projectId: "1",
          projectName: "Alpha",
          projectColor: "#111111",
          insightType: "risk_supplier",
          severity: "warning",
          title: "Alpha risk card",
          summary: "s",
          chart: null,
          callout: null,
          sources: { tables: [], documents: [] },
          executedAt: "2026-06-25T00:00:00Z",
        },
      ],
    },
    {
      projectId: "2",
      projectName: "Beta",
      projectColor: "#222222",
      insights: [
        {
          id: "b1",
          projectId: "2",
          projectName: "Beta",
          projectColor: "#222222",
          insightType: "trend_spend",
          severity: "recommendation",
          title: "Beta trend card",
          summary: "s",
          chart: null,
          callout: null,
          sources: { tables: [], documents: [] },
          executedAt: "2026-06-25T00:00:00Z",
        },
      ],
    },
  ],
  synthesis: null,
};

function sidebarProjectRow(name: string): HTMLElement {
  // "Projects at a glance" list lives in the sidebar <aside>; scope there so
  // the matcher doesn't also hit the insight cards in the main column.
  const aside = document.querySelector("aside") as HTMLElement;
  return within(aside).getByRole("button", { name: new RegExp(name) });
}

describe("IntelligenceFeed refresh state", () => {
  beforeEach(() => {
    push.mockReset();
    streamHomeIntelligence.mockReset();
    getPreferences.mockReset();
    getIntelligenceSnapshot.mockReset();
    updatePreferences.mockReset();
    lastOnEvent = null;

    streamHomeIntelligence.mockReturnValue(new AbortController());
    updatePreferences.mockResolvedValue({});
    // run_on_load false so hydration settles (counts shown) before we drive a
    // refresh manually via the button.
    getPreferences.mockResolvedValue({
      intelligence: {
        run_on_load: false,
        cross_project: true,
        email_digest: false,
        granularity: 3,
      },
    });
    getIntelligenceSnapshot.mockResolvedValue({ snapshot: SNAPSHOT });
  });

  it("marks every sidebar project Analyzing on refresh, then only the completed one returns", async () => {
    render(<IntelligenceFeed />);

    // Hydrated from snapshot: both projects show their insight counts.
    await waitFor(() =>
      expect(sidebarProjectRow("Alpha")).toBeTruthy(),
    );
    await waitFor(() =>
      expect(within(sidebarProjectRow("Alpha")).getByText(/insight/)).toBeTruthy(),
    );

    // Refresh: background re-run keeps visible cards, resets freshCompleted.
    act(() => {
      screen
        .getByRole("button", { name: /refresh intelligence/i })
        .click();
    });
    await waitFor(() => expect(lastOnEvent).toBeTruthy());
    act(() => {
      lastOnEvent!({ type: "start", projects: PROJECTS });
    });

    // During refresh, every project shows "Analyzing" (freshCompleted empty).
    await waitFor(() =>
      expect(
        within(sidebarProjectRow("Alpha")).getByText("Analyzing"),
      ).toBeTruthy(),
    );
    expect(
      within(sidebarProjectRow("Beta")).getByText("Analyzing"),
    ).toBeTruthy();

    // One project reports in — only it leaves the Analyzing state.
    act(() => {
      lastOnEvent!({
        type: "project_complete",
        projectId: "1",
        projectName: "Alpha",
        projectColor: "#111111",
        insights: [],
      });
    });

    await waitFor(() =>
      expect(
        within(sidebarProjectRow("Alpha")).queryByText("Analyzing"),
      ).toBeNull(),
    );
    expect(
      within(sidebarProjectRow("Beta")).getByText("Analyzing"),
    ).toBeTruthy();

    // Visible cards are unchanged mid-refresh (background buffer not committed).
    expect(screen.getByText("Alpha risk card")).toBeTruthy();
    expect(screen.getByText("Beta trend card")).toBeTruthy();
  });
});

describe("IntelligenceStrip cleanup", () => {
  beforeEach(() => {
    push.mockReset();
    streamHomeIntelligence.mockReset();
    getPreferences.mockReset();
    getIntelligenceSnapshot.mockReset();
    lastOnEvent = null;
    streamHomeIntelligence.mockReturnValue(new AbortController());
    getPreferences.mockResolvedValue({
      intelligence: {
        run_on_load: false,
        cross_project: true,
        email_digest: false,
        granularity: 3,
      },
    });
    getIntelligenceSnapshot.mockResolvedValue({ snapshot: null });
  });

  it("keeps the Depth slider and refresh control but drops sparkles/status text", async () => {
    render(<IntelligenceFeed />);

    // Depth slider + refresh remain.
    await waitFor(() =>
      expect(screen.getByLabelText("Insight granularity")).toBeTruthy(),
    );
    expect(screen.getByText("Depth")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /refresh intelligence/i }),
    ).toBeTruthy();

    // Status text removed.
    expect(screen.queryByText(/AI analyzed/)).toBeNull();
    expect(screen.queryByText(/AI running across/)).toBeNull();
    expect(screen.queryByText(/Gathering insights/)).toBeNull();
  });
});
