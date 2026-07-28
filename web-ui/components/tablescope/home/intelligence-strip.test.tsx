import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IntelligenceStrip, type FilterableProject } from "./intelligence-strip";

const PROJECTS: FilterableProject[] = [
  { id: "1", name: "Alpha", accent: "#123456" },
  { id: "2", name: "Beta", accent: "#654321" },
];

const handlers = {
  onRefresh: vi.fn(),
  onClearCache: vi.fn(),
  onToggleProject: vi.fn(),
  onSelectAll: vi.fn(),
  onClear: vi.fn(),
  onGranularityChange: vi.fn(),
};

function renderStrip(props: Partial<Parameters<typeof IntelligenceStrip>[0]> = {}) {
  return render(
    <IntelligenceStrip
      projectCount={2}
      totalProjectCount={2}
      running={false}
      lastUpdatedLabel="Updated just now"
      granularity={3}
      availableProjects={PROJECTS}
      selectedProjectIds={new Set(["1", "2"])}
      {...handlers}
      {...props}
    />,
  );
}

describe("IntelligenceStrip", () => {
  it("does not render a blue analysis banner", () => {
    const { container } = renderStrip();
    expect(container.querySelector(".bg-brand")).toBeNull();
    expect(screen.queryByText(/AI analyzed/)).toBeNull();
  });

  it("shows project filter, depth, last updated, clear and refresh in one toolbar", () => {
    renderStrip();
    expect(screen.getByRole("button", { name: /Filter by project/i })).toBeTruthy();
    expect(screen.getByLabelText(/Insight granularity/i)).toBeTruthy();
    expect(screen.getByText("Balanced")).toBeTruthy();
    expect(screen.getByText("Updated just now")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Clear Business Insight cache/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Refresh intelligence/i })).toBeTruthy();
  });

  it("displays an analyzing status while running", () => {
    renderStrip({ running: true, projectCount: 11 });
    expect(screen.getByText("Analyzing 11 projects…")).toBeTruthy();
    expect(screen.queryByText("Analyzing 11 project")).toBeNull();
  });

  it("calls the refresh handler", () => {
    renderStrip();
    fireEvent.click(screen.getByRole("button", { name: /Refresh intelligence/i }));
    expect(handlers.onRefresh).toHaveBeenCalledTimes(1);
  });

  it("calls the clear-cache handler and respects the disabled state", () => {
    const { rerender } = renderStrip({ isClearingCache: false });
    const clearButton = screen.getByRole("button", { name: /Clear Business Insight cache/i });
    expect(clearButton.disabled).toBe(false);
    fireEvent.click(clearButton);
    expect(handlers.onClearCache).toHaveBeenCalledTimes(1);

    rerender(
      <IntelligenceStrip
        projectCount={2}
        totalProjectCount={2}
        running={false}
        lastUpdatedLabel="Updated just now"
        granularity={3}
        availableProjects={PROJECTS}
        selectedProjectIds={new Set(["1", "2"])}
        {...handlers}
        isClearingCache
      />,
    );
    expect(screen.getByRole("button", { name: /Clear Business Insight cache/i }).disabled).toBe(true);
  });

  it("updates the depth value", () => {
    renderStrip({ granularity: 3 });
    const slider = screen.getByLabelText(/Insight granularity/i);
    fireEvent.change(slider, { target: { value: "5" } });
    expect(handlers.onGranularityChange).toHaveBeenCalledWith(5);
  });

  it("shows a filtered project count", () => {
    renderStrip({ projectCount: 1, totalProjectCount: 2 });
    expect(screen.getByText("1 of 2 projects")).toBeTruthy();
  });
});
