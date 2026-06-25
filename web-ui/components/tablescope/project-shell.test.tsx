import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
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
  AppShell: ({ topBarLeft, children }: { topBarLeft: React.ReactNode; children: React.ReactNode }) => (
    <div>
      <div>{topBarLeft}</div>
      {children}
    </div>
  ),
}));

import { ProjectShell } from "./project-shell";

describe("ProjectShell back navigation", () => {
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
});
