import { describe, expect, it, vi } from "vitest";
import { render, renderHook, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsNav, useSettingsNavItems } from "./settings-nav";
import type { CurrentUser, ProjectSummary } from "@/lib/ui/types";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/settings/data-source-assignments",
  useRouter: () => ({ push, replace: vi.fn() }),
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: () => ({
    data: [
      { id: "7", name: "Boeing 787", visibility: "shared", updatedLabel: "today", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "ready" },
      { id: "8", name: "Airbus A350", visibility: "shared", updatedLabel: "today", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "ready" },
    ] as ProjectSummary[],
    isLoading: false,
  }),
  useCurrentUser: () => ({
    data: {
      user: { id: 1, name: "Admin", email: "admin@tablescope.cloud" } as CurrentUser,
      tenant: { name: "Acme", slug: "acme", initials: "A" },
    },
    isLoading: false,
  }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSettingsNavItems", () => {
  it("places Data Source Assignments under Integrations", () => {
    const { result } = renderHook(() => useSettingsNavItems({
      id: 1,
      name: "Admin",
      email: "admin@tablescope.cloud",
      role: "admin",
      rawRole: "admin",
      tenantName: "Acme",
      initials: "A",
      isSuperAdmin: false,
      avatarUrl: null,
    } as CurrentUser), { wrapper });

    const integrations = result.current.sections.find(
      (s) => s.heading === "Integrations",
    );
    expect(integrations?.items.map((i) => i.key)).toContain(
      "data-source-assignments",
    );
  });

  it("includes a Project Intelligence section for regular users", () => {
    const { result } = renderHook(() => useSettingsNavItems({
      id: 2,
      name: "Member",
      email: "member@tablescope.cloud",
      role: "member",
      rawRole: "member",
      tenantName: "Acme",
      initials: "M",
      isSuperAdmin: false,
      avatarUrl: null,
    } as CurrentUser), { wrapper });

    const pi = result.current.sections.find(
      (s) => s.heading === "Project Intelligence",
    );
    expect(pi).toBeDefined();
    expect(pi?.items.map((i) => i.label)).toEqual([
      "Graph Lifecycle",
      "Metadata Catalog",
      "Project Reference Library",
      "Audit Log",
    ]);
  });

  it("shows Project Intelligence sub-links when a project is selected", () => {
    localStorage.setItem(
      "tablescope:last-project-intelligence:acme:1",
      "7",
    );
    const { result } = renderHook(() => useSettingsNavItems({
      id: 1,
      name: "Admin",
      email: "admin@tablescope.cloud",
      role: "admin",
      rawRole: "admin",
      tenantName: "Acme",
      initials: "A",
      isSuperAdmin: false,
      avatarUrl: null,
    } as CurrentUser), { wrapper });

    const pi = result.current.sections.find(
      (s) => s.heading === "Project Intelligence",
    );
    expect(pi?.items[0].href).toBe(
      "/admin/settings/project-intelligence/7/graph-lifecycle",
    );
    localStorage.removeItem("tablescope:last-project-intelligence:acme:1");
  });
});

describe("SettingsNav", () => {
  it("renders Data Source Assignments in the mobile select", () => {
    render(
      <SettingsNav
        user={{
          id: 1,
          name: "Admin",
          email: "admin@tablescope.cloud",
          role: "admin",
          rawRole: "admin",
          tenantName: "Acme",
          initials: "A",
          isSuperAdmin: false,
          avatarUrl: null,
        }}
      />,
      { wrapper },
    );
    expect(screen.getByRole("option", { name: "Data Source Assignments" })).toBeInTheDocument();
  });
});
