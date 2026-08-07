import { describe, expect, it, vi } from "vitest";
import { render, screen, renderHook, waitFor } from "@testing-library/react";
import {
  ProjectIntelligenceProvider,
  useProjectIntelligence,
} from "./project-intelligence-context";
import type { CurrentUser, ProjectSummary } from "@/lib/ui/types";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/admin/settings/project-intelligence/7/graph-lifecycle",
  useParams: () => ({ projectId: "7" }),
  useSearchParams: () => new URLSearchParams(),
}));

const mockSummaries: ProjectSummary[] = [
  { id: "7", name: "Boeing 787", visibility: "shared", updatedLabel: "today", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "ready" },
  { id: "8", name: "Airbus A350", visibility: "shared", updatedLabel: "today", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "ready" },
];

vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: () => ({ data: mockSummaries, isLoading: false }),
  useCurrentUser: () => ({
    data: {
      user: { id: 1, name: "Admin", email: "admin@tablescope.cloud" } as CurrentUser,
      tenant: { name: "Acme", slug: "acme", initials: "A" },
    },
    isLoading: false,
  }),
}));

function Provider({
  routeProjectId,
  children,
}: {
  routeProjectId: string;
  children: React.ReactNode;
}) {
  return (
    <ProjectIntelligenceProvider routeProjectId={routeProjectId}>
      {children}
    </ProjectIntelligenceProvider>
  );
}

function ProjectName() {
  const { project } = useProjectIntelligence();
  return <div data-testid="project">{project?.name ?? "none"}</div>;
}

function InvalidFlag() {
  const { isInvalid } = useProjectIntelligence();
  return <div data-testid="invalid">{isInvalid ? "true" : "false"}</div>;
}

describe("ProjectIntelligenceProvider", () => {
  it("resolves the project from the route param", () => {
    render(
      <Provider routeProjectId="7">
        <ProjectName />
      </Provider>,
    );
    expect(screen.getByTestId("project").textContent).toBe("Boeing 787");
  });

  it("marks an inaccessible project as invalid", () => {
    render(
      <Provider routeProjectId="99">
        <InvalidFlag />
      </Provider>,
    );
    expect(screen.getByTestId("invalid").textContent).toBe("true");
  });

  it("navigates within the same section when changing projects", async () => {
    const { result } = renderHook(() => useProjectIntelligence(), {
      wrapper: ({ children }) => (
        <Provider routeProjectId="7">{children}</Provider>
      ),
    });
    result.current.setProjectId("8", "metadata-catalog");
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(
        "/admin/settings/project-intelligence/8/metadata-catalog",
      ),
    );
  });

  it("persists the selection to tenant/user namespaced local storage", async () => {
    const { result } = renderHook(() => useProjectIntelligence(), {
      wrapper: ({ children }) => (
        <Provider routeProjectId="7">{children}</Provider>
      ),
    });
    result.current.setProjectId("8", "graph-lifecycle");
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(
        "/admin/settings/project-intelligence/8/graph-lifecycle",
      ),
    );
    const stored = localStorage.getItem(
      "tablescope:last-project-intelligence:acme:1",
    );
    expect(stored).toBe("8");
  });
});
