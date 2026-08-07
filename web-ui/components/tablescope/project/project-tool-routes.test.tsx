import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "7" }),
  useSearchParams: () => new URLSearchParams("intent=database"),
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/projects/7/data-source-builder",
}));

vi.mock("@/lib/auth", () => ({
  getUserMeta: () => ({ tenantSlug: "acme" }),
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useCurrentUser: () => ({
    data: {
      user: { id: 1, name: "Admin", email: "admin@tablescope.cloud" },
      tenant: { name: "Acme", slug: "acme", initials: "A" },
    },
    isLoading: false,
  }),
  useProjectSummaries: () => ({
    data: [{ id: "7", name: "Boeing 787", slug: "boeing-787" }],
    isLoading: false,
  }),
}));

vi.mock("@/components/tablescope/project/project-tool-screen", () => ({
  ProjectToolScreen: (props: {
    projectId: string;
    activeNav: string;
    breadcrumbLabel: string;
    children: ReactNode;
  }) => (
    <div data-testid="tool-screen" data-active={props.activeNav} data-label={props.breadcrumbLabel}>
      {props.children}
    </div>
  ),
}));

vi.mock("@/components/tablescope/data-source-builder/workspace", () => ({
  DataSourceBuilderWorkspace: (props: {
    tenantName: string;
    initialProjectId: string;
    intent?: string;
  }) => (
    <div data-testid="builder" data-tenant={props.tenantName} data-project={props.initialProjectId} data-intent={props.intent}>
      builder
    </div>
  ),
}));

vi.mock("@/components/tablescope/database-connectors/workspace", () => ({
  DatabaseConnectorsWorkspace: (props: { projectId?: string }) => (
    <div data-testid="connectors" data-project={props.projectId}>
      connectors
    </div>
  ),
}));

import ProjectDataSourceBuilderPage from "@/app/projects/[id]/data-source-builder/page";
import ProjectDatabaseConnectorsPage from "@/app/projects/[id]/database-connectors/page";

describe("project tool routes", () => {
  it("renders the project-scoped Data Source Builder with the right props", () => {
    render(<ProjectDataSourceBuilderPage />);
    const toolScreen = screen.getByTestId("tool-screen");
    expect(toolScreen.getAttribute("data-active")).toBe("project-data-source-builder");
    expect(toolScreen.getAttribute("data-label")).toBe("Data Source Builder");
    const builder = screen.getByTestId("builder");
    expect(builder.getAttribute("data-project")).toBe("7");
    expect(builder.getAttribute("data-intent")).toBe("database");
  });

  it("renders the project-scoped Database Connectors route", () => {
    render(<ProjectDatabaseConnectorsPage />);
    const toolScreen = screen.getByTestId("tool-screen");
    expect(toolScreen.getAttribute("data-active")).toBe("project-database-connectors");
    expect(toolScreen.getAttribute("data-label")).toBe("Database Connectors");
    const connectors = screen.getByTestId("connectors");
    expect(connectors.getAttribute("data-project")).toBe("7");
  });
});
