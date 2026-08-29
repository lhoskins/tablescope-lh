import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProjectNavGrid } from "./project-nav-grid";

describe("ProjectNavGrid", () => {
  it("renders all twelve cards pointed at the project", () => {
    render(<ProjectNavGrid projectId="7" activeNav="overview" />);
    for (const label of [
      "Overview",
      "Workspace",
      "Tables",
      "Documents",
      "Dashboards",
      "Data Sources",
      "Project Insights",
      "Project Actions",
      "Reference",
      "Scopes",
      "Knowledge Graph",
      "Chats",
    ]) {
      const link = screen.getByRole("link", { name: new RegExp(label) });
      expect(link).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: /Chats/ }).getAttribute("href")).toBe(
      "/projects/7/chats",
    );
  });

  it("marks the active card with aria-current", () => {
    render(<ProjectNavGrid projectId="7" activeNav="project-queries" />);
    expect(screen.getByRole("link", { name: /Tables/ }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("link", { name: /Overview/ }).getAttribute("aria-current")).toBeNull();
  });

  it("does not render an APIs card", () => {
    render(<ProjectNavGrid projectId="7" activeNav="overview" />);
    expect(screen.queryByRole("link", { name: /APIs/ })).toBeNull();
  });
});
