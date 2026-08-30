import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

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
  useProjectMembers: () => ({ data: [] }),
}));

vi.mock("./project/project-topbar", () => ({
  ProjectTitleBreadcrumb: ({ screenLabel }: { screenLabel?: string }) => (
    <div data-testid="project-title">Boeing › {screenLabel}</div>
  ),
  ProjectTopBarControls: ({ actions }: { actions?: ReactNode }) => (
    <div data-testid="project-controls">
      {actions}
      Private Members
    </div>
  ),
}));

vi.mock("./project/members-dialog", () => ({
  MembersDialog: () => null,
}));

vi.mock("./app-shell", () => ({
  AppShell: ({
    topBarLeft,
    topBarControls,
    subHeader,
    children,
  }: {
    topBarLeft?: ReactNode;
    topBarControls?: ReactNode;
    subHeader?: ReactNode;
    children: ReactNode;
  }) => (
    <div>
      <div data-testid="top-bar">
        {topBarLeft}
        {topBarControls}
      </div>
      <div data-testid="sub-header">{subHeader}</div>
      {children}
    </div>
  ),
}));

import { ProjectShell } from "./project-shell";

describe("ProjectShell", () => {
  it("puts the project title, screen name and project controls in the top bar", () => {
    render(
      <ProjectShell projectId="7" activeNav="project-data-sources" breadcrumbLabel="Data Sources">
        <div>body</div>
      </ProjectShell>,
    );
    const topBar = screen.getByTestId("top-bar");
    expect(topBar).toHaveTextContent("Boeing › Data Sources");
    expect(topBar).toHaveTextContent("Private");
    expect(topBar).toHaveTextContent("Members");
  });

  it("falls back to the nav card's label when a screen passes no breadcrumb", () => {
    render(
      <ProjectShell projectId="7" activeNav="workspace">
        <div>body</div>
      </ProjectShell>,
    );
    expect(screen.getByTestId("top-bar")).toHaveTextContent("Boeing › Workspace");
  });

  it("hands page actions to the top bar rather than a separate toolbar row", () => {
    render(
      <ProjectShell
        projectId="7"
        activeNav="project-queries"
        breadcrumbLabel="Tables"
        actions={<button type="button">Create Query with AI</button>}
      >
        <div>body</div>
      </ProjectShell>,
    );
    const topBar = screen.getByTestId("top-bar");
    expect(within(topBar).getByRole("button", { name: "Create Query with AI" })).toBeTruthy();
  });

  it("renders the same nav grid sub-header on every project screen, overview included", () => {
    for (const activeNav of ["overview", "project-data-sources"] as const) {
      const { unmount } = render(
        <ProjectShell projectId="7" activeNav={activeNav}>
          <div>body</div>
        </ProjectShell>,
      );
      const subHeader = screen.getByTestId("sub-header");
      for (const label of ["Overview", "Data Sources", "Tables", "Documents", "Dashboards"]) {
        expect(within(subHeader).getByRole("link", { name: new RegExp(label) })).toBeTruthy();
      }
      unmount();
    }
  });
});
