import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IntelligenceCard } from "./intelligence-card";
import type { InsightCard as InsightCardData } from "@/lib/api/home-intelligence";

vi.mock("@/lib/ui/use-shell-data", () => ({ useCurrentUser: () => ({ data: null }) }));
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
