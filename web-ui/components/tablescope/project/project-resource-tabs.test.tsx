import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => mockedPathname,
}));

import { ProjectResourceTabs } from "./project-resource-tabs";

let mockedPathname = "/projects/7";

describe("ProjectResourceTabs", () => {
  it("renders the five resource tabs in order", () => {
    mockedPathname = "/projects/7";
    render(<ProjectResourceTabs projectId="7" />);
    const tabs = screen.getAllByRole("link");
    expect(tabs.map((t) => t.textContent)).toEqual([
      "Overview",
      "Data Sources",
      "Tables",
      "Documents",
      "Dashboards",
    ]);
  });

  it("marks Overview active on the canonical project route", () => {
    mockedPathname = "/projects/7";
    render(<ProjectResourceTabs projectId="7" />);
    const overview = screen.getByRole("link", { name: /Overview/ });
    expect(overview).toHaveAttribute("aria-current", "page");
  });

  it("marks Data Sources active for nested detail routes", () => {
    mockedPathname = "/projects/7/data-sources/some-source";
    render(<ProjectResourceTabs projectId="7" />);
    const tab = screen.getByRole("link", { name: /Data Sources/ });
    expect(tab).toHaveAttribute("aria-current", "page");
  });

  it("does not mark Overview active on a resource route", () => {
    mockedPathname = "/projects/7/queries";
    render(<ProjectResourceTabs projectId="7" />);
    const overview = screen.getByRole("link", { name: /Overview/ });
    expect(overview).not.toHaveAttribute("aria-current");
  });

  it("renders text-only tabs with no icons", () => {
    mockedPathname = "/projects/7";
    const { container } = render(<ProjectResourceTabs projectId="7" />);
    expect(container.querySelectorAll("svg")).toHaveLength(0);
  });

  it("uses the darker neutral token for inactive tabs and hover/focus states", () => {
    mockedPathname = "/projects/7";
    render(<ProjectResourceTabs projectId="7" />);
    const documents = screen.getByRole("link", { name: "Documents" });
    expect(documents.className).toContain("text-ink-secondary");
    expect(documents.className).toContain("hover:text-ink-primary");
    expect(documents.className).toContain("focus-visible:ring-brand-500");
    expect(documents.className).not.toContain("text-ink-tertiary");
  });

  it("marks the active tab with the strongest neutral plus an underline", () => {
    mockedPathname = "/projects/7";
    render(<ProjectResourceTabs projectId="7" />);
    const overview = screen.getByRole("link", { name: "Overview" });
    expect(overview.className).toContain("text-ink-primary");
    expect(overview.querySelector("span.bg-brand-500")).not.toBeNull();
  });
});
