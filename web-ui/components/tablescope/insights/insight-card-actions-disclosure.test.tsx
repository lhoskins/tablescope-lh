import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InsightCardActionsDisclosure } from "./insight-card-actions-disclosure";

describe("InsightCardActionsDisclosure", () => {
  it("defaults to collapsed and shows a More Actions button", () => {
    render(
      <InsightCardActionsDisclosure
        insightId="i1"
        sources={<span>Source 1</span>}
        actions={<button type="button">Action</button>}
      />,
    );

    const toggle = screen.getByRole("button", { name: /More Actions/i });
    expect(toggle).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.getAttribute("aria-controls")).toBeTruthy();

    expect(screen.queryByText("Source 1")).toBeNull();
    expect(screen.queryByRole("button", { name: "Action" })).toBeNull();
  });

  it("displays a downward chevron when collapsed", () => {
    render(
      <InsightCardActionsDisclosure insightId="i1" actions={<div>Action</div>} />,
    );
    const toggle = screen.getByRole("button", { name: /More Actions/i });
    expect(toggle.querySelector("svg")).toBeTruthy();
  });

  it("expands to show sources, a divider, and actions when clicked", () => {
    render(
      <InsightCardActionsDisclosure
        insightId="i1"
        sources={<span data-testid="source">Source 1</span>}
        actions={<button type="button">Action</button>}
      />,
    );

    const toggle = screen.getByRole("button", { name: /More Actions/i });
    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTestId("source")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Action" })).toBeTruthy();
  });

  it("collapses again when the expanded toggle is clicked", () => {
    render(
      <InsightCardActionsDisclosure
        insightId="i1"
        sources={<span>Source 1</span>}
        actions={<button type="button">Action</button>}
      />,
    );

    const toggle = screen.getByRole("button", { name: /More Actions/i });
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Source 1")).toBeNull();
  });

  it("generates unique aria-controls targets for multiple cards", () => {
    render(
      <>
        <InsightCardActionsDisclosure
          insightId="i1"
          actions={<button type="button">A</button>}
        />
        <InsightCardActionsDisclosure
          insightId="i2"
          actions={<button type="button">B</button>}
        />
      </>,
    );

    const toggles = screen.getAllByRole("button", { name: /More Actions/i });
    const controls1 = toggles[0].getAttribute("aria-controls");
    const controls2 = toggles[1].getAttribute("aria-controls");
    expect(controls1).toBeTruthy();
    expect(controls2).toBeTruthy();
    expect(controls1).not.toBe(controls2);

    fireEvent.click(toggles[0]);
    fireEvent.click(toggles[1]);

    const content1 = document.getElementById(controls1 as string);
    const content2 = document.getElementById(controls2 as string);
    expect(content1).toBeTruthy();
    expect(content2).toBeTruthy();
    expect(content1).not.toBe(content2);
  });

  it("renders only the action row when no sources are provided", () => {
    render(
      <InsightCardActionsDisclosure
        insightId="i1"
        actions={<button type="button">Action</button>}
      />,
    );

    const toggle = screen.getByRole("button", { name: /More Actions/i });
    fireEvent.click(toggle);

    expect(screen.getByRole("button", { name: "Action" })).toBeTruthy();
    const content = document.getElementById(
      toggle.getAttribute("aria-controls") as string,
    );
    expect(content?.querySelectorAll("div").length).toBeGreaterThan(0);
  });

  it("calls action handlers when expanded and clicked", () => {
    const handler = vi.fn();
    render(
      <InsightCardActionsDisclosure
        insightId="i1"
        sources={<span>Source</span>}
        actions={<button type="button" onClick={handler}>Action</button>}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /More Actions/i }));
    fireEvent.click(screen.getByRole("button", { name: "Action" }));
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
