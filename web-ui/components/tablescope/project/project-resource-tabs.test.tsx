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
});
