import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/projects/7",
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
    topBarLeft,
    subHeader,
    children,
  }: {
    topBarLeft: React.ReactNode;
    subHeader?: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div>
      <div>{topBarLeft}</div>
      <div data-testid="sub-header">{subHeader}</div>
      {children}
    </div>
  ),
}));

import { ProjectShell } from "./project-shell";

describe("ProjectShell", () => {
  beforeEach(() => push.mockClear());

  it("renders a back-to-projects button that routes to /projects", () => {
    render(
      <ProjectShell projectId="7" activeNav="overview" breadcrumbLabel="Overview">
        <div>body</div>
      </ProjectShell>,
    );
    const back = screen.getByRole("button", { name: "Back to projects" });
    fireEvent.click(back);
    expect(push).toHaveBeenCalledWith("/projects");
  });

  it("renders project resource tabs in the sub-header", () => {
    render(
      <ProjectShell projectId="7" activeNav="overview" breadcrumbLabel="Overview">
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
});
