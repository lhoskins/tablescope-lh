import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProjectsTree } from "./projects-tree";

const projects = [
  { id: "1", name: "Mine Only", visibility: "private", accent: "#111", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "idle", updatedLabel: "" },
  { id: "2", name: "Team Rollup", visibility: "shared", accent: "#222", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "idle", updatedLabel: "" },
  { id: "3", name: "Also Shared", visibility: "shared", accent: "#333", documentCount: 0, queryCount: 0, dashboardCount: 0, aiStatus: "idle", updatedLabel: "" },
];

vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: () => ({ data: projects }),
}));

vi.mock("@/lib/ui/use-project-data", () => ({
  useProjectQueries: () => ({ data: [{ id: 5, name: "Orders" }] }),
  useProjectDocuments: () => ({ data: [{ id: 9, title: "Spec.pdf" }] }),
  useProjectDataSources: () => ({ data: [{ id: 11, fileName: "Salesforce", lifecycleId: "11" }] }),
}));

vi.mock("@/components/tablescope/project/workspace/workspace-tabs-storage", () => ({
  loadWorkspaceTabs: (projectId: string) =>
    projectId === "2" ? [{ type: "table", id: "5", label: "Orders", href: "/x" }] : [],
}));

function renderTree(currentProjectId?: string) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <ProjectsTree currentProjectId={currentProjectId} collapsed={false} />
    </QueryClientProvider>,
  );
}

describe("ProjectsTree", () => {
  it("is a disclosure toggle, closed by default outside a project", () => {
    renderTree();
    expect(screen.queryByText("Mine Only")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Projects/ }));
    expect(screen.getByText("Mine Only")).toBeTruthy();
  });

  it("groups projects into PRIVATE and SHARED, uncapped", () => {
    renderTree();
    fireEvent.click(screen.getByRole("button", { name: /Projects/ }));
    expect(screen.getByText(/PRIVATE \(1\)/)).toBeTruthy();
    expect(screen.getByText(/SHARED \(2\)/)).toBeTruthy();
    expect(screen.getByText("Also Shared")).toBeTruthy();
  });

  it("auto-expands the current project's asset subtree", async () => {
    renderTree("2");
    expect(screen.getByText("Team Rollup")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Tables/ }));
    await waitFor(() => expect(screen.getByText("Orders")).toBeTruthy());
    // Pinned into the workspace tab strip for project 2 -- highlighted.
    expect(screen.getByText("Orders").className).toContain("text-brand-500");
  });

  it("only renders an asset subtree for the current project, not the other two", () => {
    renderTree("2");
    expect(screen.getAllByRole("button", { name: /^Documents/ })).toHaveLength(1);
  });
});
