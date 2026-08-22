import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DimensionSwitcher } from "./dimension-switcher";

describe("DimensionSwitcher", () => {
  it("renders nothing with zero or one assigned dimension", () => {
    const { container: empty } = render(<DimensionSwitcher options={[]} onSelect={vi.fn()} />);
    expect(empty.textContent).toBe("");

    const { container: single } = render(
      <DimensionSwitcher options={[{ id: 1, label: "Business Unit", isActive: true }]} onSelect={vi.fn()} />,
    );
    expect(single.textContent).toBe("");
  });

  it("shows a switch icon and lists every full-coverage dimension when there are two or more", () => {
    render(
      <DimensionSwitcher
        options={[
          { id: 1, label: "Business Unit", isActive: true },
          { id: 2, label: "Customer Segment", isActive: false },
        ]}
        onSelect={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("button", { name: /Switch primary dimension/i });
    fireEvent.click(toggle);

    expect(screen.getByText("Business Unit")).toBeTruthy();
    expect(screen.getByText("Customer Segment")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
  });

  it("selecting the inactive dimension calls onSelect with its id and closes the menu", () => {
    const onSelect = vi.fn();
    render(
      <DimensionSwitcher
        options={[
          { id: 1, label: "Business Unit", isActive: true },
          { id: 2, label: "Customer Segment", isActive: false },
        ]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Switch primary dimension/i }));
    fireEvent.click(screen.getByText("Customer Segment"));

    expect(onSelect).toHaveBeenCalledWith(2);
    expect(screen.queryByText("Business Unit")).toBeNull();
  });

  it("selecting the already-active dimension does not call onSelect", () => {
    const onSelect = vi.fn();
    render(
      <DimensionSwitcher
        options={[
          { id: 1, label: "Business Unit", isActive: true },
          { id: 2, label: "Customer Segment", isActive: false },
        ]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Switch primary dimension/i }));
    fireEvent.click(screen.getByText("Business Unit"));

    expect(onSelect).not.toHaveBeenCalled();
  });
});
