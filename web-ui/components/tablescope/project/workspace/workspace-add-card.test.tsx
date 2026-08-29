import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WorkspaceAddCard } from "./workspace-add-card";
import type { WorkspaceCard } from "@/lib/api/workspaces";

const queriesData = vi.hoisted(() => ({ rows: [] as unknown[] }));
const dashboardsData = vi.hoisted(() => ({ rows: [] as unknown[] }));
const documentsData = vi.hoisted(() => ({ rows: [] as unknown[] }));
const dataSourcesData = vi.hoisted(() => ({ rows: [] as unknown[] }));

vi.mock("@/lib/ui/use-project-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/ui/use-project-data")>();
  return {
    ...actual,
    useProjectQueries: () => ({ data: queriesData.rows }),
    useProjectDashboards: () => ({ data: dashboardsData.rows }),
    useProjectDocuments: () => ({ data: documentsData.rows }),
    useProjectDataSources: () => ({ data: dataSourcesData.rows }),
  };
});

describe("WorkspaceAddCard", () => {
  const cards: WorkspaceCard[] = [];

  it("offers database and SaaS sources, but not file sources without a numeric id", () => {
    dataSourcesData.rows = [
      { id: 11, fileName: "Orders DB", sourceType: "database_table", lifecycleKind: "database", lifecycleId: "11" },
      { id: 12, fileName: "Salesforce Leads", sourceType: "saas_object", lifecycleKind: "saas", lifecycleId: "12" },
      { fileName: "Uploaded CSV", sourceType: "csv", lifecycleKind: "file", lifecycleId: "Uploaded_CSV" },
    ];
    queriesData.rows = [];
    dashboardsData.rows = [];
    documentsData.rows = [];

    render(<WorkspaceAddCard projectId="7" cards={cards} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add card" }));

    expect(screen.getByRole("button", { name: /Orders DB/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Salesforce Leads/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Uploaded CSV/ })).toBeNull();
  });

  it("adds a data source card with the DatabaseDataSource id as resource_id", () => {
    dataSourcesData.rows = [
      { id: 11, fileName: "Orders DB", sourceType: "database_table", lifecycleKind: "database", lifecycleId: "11" },
    ];
    queriesData.rows = [];
    dashboardsData.rows = [];
    documentsData.rows = [];

    const onAdd = vi.fn();
    render(<WorkspaceAddCard projectId="7" cards={cards} onAdd={onAdd} />);
    fireEvent.click(screen.getByRole("button", { name: "Add card" }));
    fireEvent.click(screen.getByRole("button", { name: /Orders DB/ }));

    expect(onAdd).toHaveBeenCalledWith({
      resource_type: "data_source",
      resource_id: "11",
      label: "Orders DB",
    });
  });
});
