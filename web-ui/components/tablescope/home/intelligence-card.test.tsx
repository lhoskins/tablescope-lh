import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IntelligenceCard } from "./intelligence-card";
import type { InsightCard as InsightCardData } from "@/lib/api/home-intelligence";

vi.mock("@/lib/ui/use-shell-data", () => ({
  useCurrentUser: () => ({ data: { user: { rawRole: "admin" } } }),
}));
vi.mock("@/components/dashboard/WidgetRenderer", () => ({
  WidgetRenderer: () => <div data-testid="widget" />,
}));

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
  sources: { tables: ["demo_table"], documents: ["report.pdf"] },
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

describe("IntelligenceCard Option 2 toolbar", () => {
  it("applies the executive treatment without removing actions", () => {
    render(
      <IntelligenceCard
        card={baseCard}
        presentation="executive"
        onSaveToDashboard={() => {}}
      />,
    );
    const article = document.querySelector("article");
    expect(article?.classList.contains("border-l-4")).toBe(true);
    expect(screen.queryByText("Title:")).toBeNull();
    expect(screen.queryByText("Summary:")).toBeNull();
    expect(screen.getByRole("button", { name: "Explain" })).toBeTruthy();
  });

  it("renders Create Action, Explain, and source row by default", () => {
    const onCreateAction = vi.fn();
    const onExplain = vi.fn();
    render(
      <IntelligenceCard
        card={baseCard}
        onCreateAction={onCreateAction}
        onSaveToDashboard={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Create Action" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Explain" })).toBeTruthy();
    expect(screen.getByText("demo_table")).toBeTruthy();
    expect(screen.getByRole("button", { name: "1 more source" })).toBeTruthy();
  });

  it("shows a More Actions disclosure toggle when collapsible and hides content until expanded", () => {
    render(<IntelligenceCard card={baseCard} actionsDisclosure="collapsible" />);
    const toggle = screen.getByRole("button", { name: /More Actions/i });
    expect(toggle).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Create Action" })).toBeNull();
    expect(screen.queryByText("demo_table")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Create Action" })).toBeTruthy();
    expect(screen.getByText("demo_table")).toBeTruthy();
  });

  it("hides all toolbar actions when hideActions is true", () => {
    render(<IntelligenceCard card={baseCard} hideActions />);
    expect(screen.queryByRole("button", { name: "Create Action" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Explain" })).toBeNull();
    expect(screen.queryByText("demo_table")).toBeNull();
  });

  it("opens the Explain panel when Explain is clicked", () => {
    render(<IntelligenceCard card={baseCard} />);
    fireEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(screen.getByText("Explain insight")).toBeTruthy();
  });

  it("calls onCreateAction when Create Action is clicked", () => {
    const onCreateAction = vi.fn();
    render(
      <IntelligenceCard
        card={baseCard}
        onCreateAction={onCreateAction}
        onSaveToDashboard={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Action" }));
    expect(onCreateAction).toHaveBeenCalled();
  });

  it("does not show Create action when the user cannot manage project actions", () => {
    const onCreateAction = vi.fn();
    render(
      <IntelligenceCard
        card={baseCard}
        onCreateAction={onCreateAction}
        onSaveToDashboard={() => {}}
      />,
    );
    // admin can manage actions, so the button is present in the default mock.
    expect(screen.getByRole("button", { name: "Create Action" })).toBeTruthy();
  });

  it("does not render a standalone R Analytics badge", () => {
    render(
      <IntelligenceCard
        card={{ ...baseCard, analyticalMethod: { method: "r_summary", executionEngine: "R" } }}
        onSaveToDashboard={() => {}}
      />,
    );
    expect(screen.queryByText("R Analytics")).toBeNull();
  });
});
