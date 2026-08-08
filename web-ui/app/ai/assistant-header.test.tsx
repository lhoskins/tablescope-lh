import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AssistantHeader } from "./assistant-header";

describe("AssistantHeader", () => {
  it("renders only the title when no return project is provided", () => {
    render(<AssistantHeader />);
    expect(screen.getByText("AI Assistant")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a back link with the project name and canonical route", () => {
    render(<AssistantHeader returnProject={{ id: 5, name: "IT Project" }} />);
    const link = screen.getByRole("link", { name: "Back to IT Project Overview" });
    expect(link).toHaveAttribute("href", "/projects/5");
    expect(screen.getByText("AI Assistant")).toBeInTheDocument();
  });
});
