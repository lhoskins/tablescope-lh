import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/7/data-sources",
}));

vi.mock("@/lib/auth", () => ({
  getUserMeta: () => ({ id: 1, email: "u@x.com" }),
}));

vi.mock("@/lib/ui/use-project-data", () => ({
  useProjectShell: () => ({
    user: { name: "User", email: "u@x.com" },
    tenant: { name: "Tenant" },
    project: { id: "7", name: "Boeing" },
    otherProjects: [],
    counts: {},
  }),
}));

vi.mock("./app-shell", () => ({
  AppShell: ({
    topBarRight,
    subHeader,
    children,
  }: {
    topBarRight?: ReactNode;
    subHeader?: ReactNode;
    children: ReactNode;
  }) => (
    <div>
      <div>{topBarRight}</div>
      <div data-testid="sub-header">{subHeader}</div>
      {children}
    </div>
  ),
}));

import { ProjectShell } from "./project-shell";

describe("ProjectShell", () => {
  it("renders project resource tabs in the sub-header for non-overview pages", () => {
    render(
      <ProjectShell projectId="7" activeNav="project-data-sources" breadcrumbLabel="Data Sources">
        <div>body</div>
      </ProjectShell>,
    );
    const subHeader = screen.getByTestId("sub-header");
    expect(subHeader).toHaveTextContent("Overview");
    expect(subHeader).toHaveTextContent("Data Sources");
    expect(subHeader).toHaveTextContent("Tables");
    expect(subHeader).toHaveTextContent("Documents");
    expect(subHeader).toHaveTextContent("Dashboards");
  });

  it("omits the sub-header tabs on the overview page", () => {
    render(
      <ProjectShell projectId="7" activeNav="overview" breadcrumbLabel="Overview">
        <div>body</div>
      </ProjectShell>,
    );
    const subHeader = screen.getByTestId("sub-header");
    expect(subHeader).toBeEmptyDOMElement();
  });
});
