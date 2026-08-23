import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DashboardTitleEditor } from "./dashboard-title-editor";

describe("DashboardTitleEditor", () => {
  it("renders the name as clickable text with no separate edit icon", () => {
    render(<DashboardTitleEditor name="Sales Operation Dashboard" onSave={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Sales Operation Dashboard" });
    expect(button).toBeTruthy();
    expect(button.querySelector("svg")).toBeNull();
  });

  it("clicking the title reveals an editable input", () => {
    render(<DashboardTitleEditor name="Sales Operation Dashboard" onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Sales Operation Dashboard" }));
    expect(screen.getByLabelText("Dashboard name")).toHaveValue("Sales Operation Dashboard");
  });

  it("saves a changed name on Enter", () => {
    const onSave = vi.fn();
    render(<DashboardTitleEditor name="Sales Operation Dashboard" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Sales Operation Dashboard" }));
    const input = screen.getByLabelText("Dashboard name");
    fireEvent.change(input, { target: { value: "Q3 Sales Health" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledWith("Q3 Sales Health");
  });

  it("saves a changed name on blur", () => {
    const onSave = vi.fn();
    render(<DashboardTitleEditor name="Sales Operation Dashboard" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Sales Operation Dashboard" }));
    const input = screen.getByLabelText("Dashboard name");
    fireEvent.change(input, { target: { value: "Q3 Sales Health" } });
    fireEvent.blur(input);
    expect(onSave).toHaveBeenCalledWith("Q3 Sales Health");
  });

  it("does not save on Escape, and reverts to the original name", () => {
    const onSave = vi.fn();
    render(<DashboardTitleEditor name="Sales Operation Dashboard" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Sales Operation Dashboard" }));
    const input = screen.getByLabelText("Dashboard name");
    fireEvent.change(input, { target: { value: "Discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sales Operation Dashboard" })).toBeTruthy();
  });

  it("does not save when the value is unchanged or blank", () => {
    const onSave = vi.fn();
    render(<DashboardTitleEditor name="Sales Operation Dashboard" onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Sales Operation Dashboard" }));
    fireEvent.keyDown(screen.getByLabelText("Dashboard name"), { key: "Enter" });
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Sales Operation Dashboard" }));
    fireEvent.change(screen.getByLabelText("Dashboard name"), { target: { value: "   " } });
    fireEvent.keyDown(screen.getByLabelText("Dashboard name"), { key: "Enter" });
    expect(onSave).not.toHaveBeenCalled();
  });
});
