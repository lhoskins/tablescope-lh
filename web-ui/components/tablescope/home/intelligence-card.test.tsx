import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IntelligenceCard } from "./intelligence-card";
import type { InsightCard as InsightCardData } from "@/lib/api/home-intelligence";

vi.mock("@/lib/ui/use-shell-data", () => ({ useCurrentUser: () => ({ data: { user: { rawRole: "admin" } } }) }));
vi.mock("@/components/dashboard/WidgetRenderer", () => ({ WidgetRenderer: () => <div data-testid="widget" /> }));

const baseCard: InsightCardData = {
  id: "card-1",
  insightId: "insight-1",
  projectId: "1",
  projectName: "Project A",
  projectColor: "#000",
  insightType: "trend",
  severity: "info",
  title: "Test insight",
  summary: "A summary",
  chart: null,
  callout: null,
  sources: { tables: [], documents: [] },
  executedAt: new Date().toISOString(),
};

describe("IntelligenceCard pin control", () => {
  it("renders Pin to Home in the header when unpinned", () => {
    const onPin = vi.fn();
    render(<IntelligenceCard card={baseCard} onPin={onPin} pinned={false} />);
    const pinBtn = screen.getByRole("button", { name: /pin to home/i });
    expect(pinBtn).toBeTruthy();
    expect(pinBtn.closest("header")).toBeTruthy();
    fireEvent.click(pinBtn);
    expect(onPin).toHaveBeenCalledWith(baseCard);
  });

  it("renders Unpin from Home in the header when pinned", () => {
    const onUnpin = vi.fn();
    render(<IntelligenceCard card={baseCard} onUnpin={onUnpin} pinned />);
    const unpinBtn = screen.getByRole("button", { name: /unpin from home/i });
    expect(unpinBtn).toBeTruthy();
    expect(unpinBtn.closest("header")).toBeTruthy();
    fireEvent.click(unpinBtn);
    expect(onUnpin).toHaveBeenCalledWith(baseCard);
  });
});

describe("IntelligenceCard actionsDisclosure=collapsible", () => {
  const collapsibleCard: InsightCardData = {
    ...baseCard,
    sources: { tables: ["demo_table"], documents: ["report.pdf"] },
  };

  it("keeps header, title, summary, severity, and pin visible while collapsed", () => {
    const onPin = vi.fn();
    render(
      <IntelligenceCard
        card={collapsibleCard}
        actionsDisclosure="collapsible"
        onPin={onPin}
      />,
    );
    expect(screen.getByText("Test insight")).toBeTruthy();
    expect(screen.getByText("A summary")).toBeTruthy();
    expect(screen.getByText("Info")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Pin to Home/i })).toBeTruthy();
  });

  it("hides sources and actions while collapsed", () => {
    render(<IntelligenceCard card={collapsibleCard} actionsDisclosure="collapsible" />);
    expect(screen.queryByText("demo_table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Explain" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Chart suggestion" })).toBeNull();
  });

  it("shows More Actions toggle and expands to reveal sources and actions", () => {
    const onCreateAction = vi.fn();
    render(
      <IntelligenceCard
        card={collapsibleCard}
        actionsDisclosure="collapsible"
        onCreateAction={onCreateAction}
        onSaveToDashboard={() => {}}
      />,
    );

    const toggle = screen.getByRole("button", { name: /More Actions/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("demo_table")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Explain" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Chart suggestion" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Action" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add to dashboard" })).toBeTruthy();
  });

  it("keeps Home/frozen cards always-visible by default", () => {
    const onPin = vi.fn();
    render(<IntelligenceCard card={collapsibleCard} onPin={onPin} />);
    expect(screen.queryByRole("button", { name: /More Actions/i })).toBeNull();
    expect(screen.getByRole("button", { name: "Explain" })).toBeTruthy();
    expect(screen.getByText("demo_table")).toBeTruthy();
  });
});
